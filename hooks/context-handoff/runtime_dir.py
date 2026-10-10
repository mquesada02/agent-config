# Shared runtime folder for the context-handoff scripts (status-line wrapper, hook, launcher).
# Standard library only. Every script that imports this module under `python3 -I` must first add its own folder to sys.path.
import fcntl
import os
import re
import secrets
import stat
import time

FOLDER_NAME = "claude-context-handoff"
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_READ_BYTES = 64 * 1024
LOCK_WAIT_SECONDS = 5
LOCK_RETRY_SECONDS = 0.01


def runtime_dir_path():
    # TMPDIR only when it is absolute; the fallback ignores TEMP, TMP and the working directory so that every script resolves the same folder.
    tmpdir = os.environ.get("TMPDIR")
    base = tmpdir if tmpdir and os.path.isabs(tmpdir) else "/tmp"
    return os.path.join(base, FOLDER_NAME)


def valid_session_id(session_id):
    return isinstance(session_id, str) and SESSION_ID_PATTERN.fullmatch(session_id) is not None


def open_runtime_dir(path=None):
    """Create the folder if needed, then open it by descriptor and check it. Returns the descriptor, or None when unsafe.

    The caller closes the descriptor and does all later file work through it (dir_fd). An existing folder is never repaired.
    """
    path = path or runtime_dir_path()
    try:
        os.mkdir(path, 0o700)
    except OSError:
        pass  # exists already (or cannot be made): the open below decides
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        safe = stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and info.st_mode & 0o7777 == 0o700
    except OSError:
        safe = False
    if not safe:
        os.close(fd)
        return None
    return fd


def write_atomic(dir_fd, name, text):
    """Write text to `name` inside the folder with a temp file and a rename. The temp file is removed on any failure."""
    temp_name = secrets.token_hex(8) + ".tmp"
    file_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.rename(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except OSError:
            pass
        raise


def _open_regular_file(dir_fd, name, flags, mode=0o600):
    """Open `name` through the folder descriptor. O_NONBLOCK keeps a planted FIFO from hanging the open; only a regular file is returned."""
    file_fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, mode, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise OSError(f"{name} is not a regular file")
    except BaseException:
        os.close(file_fd)
        raise
    return file_fd


def read_file(dir_fd, name):
    """Return the UTF-8 text of `name` in the folder, or None when it does not exist.

    Raises for a file that is not a regular file, is over MAX_READ_BYTES, or is not valid UTF-8.
    """
    try:
        file_fd = _open_regular_file(dir_fd, name, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(file_fd, "rb") as handle:
        data = handle.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        raise OSError(f"{name} is over {MAX_READ_BYTES} bytes")
    return data.decode("utf-8")


def lock_file(dir_fd, name):
    """Take an exclusive lock on `name` in the folder (created if needed). Returns the descriptor; closing it releases the lock.

    Retries until LOCK_WAIT_SECONDS have passed, then raises BlockingIOError.
    """
    lock_fd = _open_regular_file(dir_fd, name, os.O_RDWR | os.O_CREAT)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock_fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(LOCK_RETRY_SECONDS)
    except BaseException:
        os.close(lock_fd)
        raise
