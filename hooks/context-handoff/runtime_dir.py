# Shared runtime folder for the context-handoff scripts (status-line wrapper, hook, launcher).
# Standard library only. Every script that imports this module under `python3 -I` must first add its own folder to sys.path.
import fcntl
import json
import os
import re
import secrets
import stat
import time

FOLDER_NAME = "claude-context-handoff"
_SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
MAX_READ_BYTES = 64 * 1024
LINEAGE_FILE = "lineage.jsonl"
LINEAGE_READ_BYTES = 4 * 1024 * 1024
LOCK_WAIT_SECONDS = 5
LOCK_RETRY_SECONDS = 0.01


def runtime_dir_path(folder_name=FOLDER_NAME):
    # TMPDIR only when it is absolute; the fallback ignores TEMP, TMP and the working directory so that every script resolves the same folder.
    # The path is normalized because the launcher refuses a runtime folder that is not.
    # The name must be one path component, so that the folder cannot leave the base.
    if folder_name in ("", ".", "..") or "/" in folder_name or "\0" in folder_name:
        raise ValueError(f"not a single folder name: {folder_name!r}")
    tmpdir = os.environ.get("TMPDIR")
    base = tmpdir if tmpdir and os.path.isabs(tmpdir) else "/tmp"
    return os.path.normpath(os.path.join(base, folder_name))


def valid_session_id(session_id):
    return isinstance(session_id, str) and _SESSION_ID_PATTERN.fullmatch(session_id) is not None


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


def _close_quietly(file_fd):
    try:
        os.close(file_fd)
    except OSError:
        pass  # a failed file-object wrap may already have closed it


def _unlink_quietly(dir_fd, name):
    try:
        os.unlink(name, dir_fd=dir_fd)
    except OSError:
        pass


def _write_temp(dir_fd, text):
    """Write text to a new temp file in the folder. Returns its name; the caller owns the file.

    A temp-name collision retries with a new name. The temp file is removed on any failure.
    """
    while True:
        temp_name = secrets.token_hex(8) + ".tmp"
        try:
            file_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)
            break
        except FileExistsError:
            continue
    try:
        try:
            handle = os.fdopen(file_fd, "w", encoding="utf-8")
        except BaseException:
            _close_quietly(file_fd)
            raise
        with handle:
            handle.write(text)
    except BaseException:
        _unlink_quietly(dir_fd, temp_name)
        raise
    return temp_name


def write_atomic(dir_fd, name, text):
    """Write text to `name` inside the folder with a temp file and a rename. The temp file is removed on any failure."""
    temp_name = _write_temp(dir_fd, text)
    try:
        os.rename(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        _unlink_quietly(dir_fd, temp_name)
        raise


def create_exclusive(dir_fd, name, text):
    """Publish `name` in the folder with the full text in one step, only if no entry of that name exists.

    Raises FileExistsError when an entry exists (file, directory, symlink or FIFO; it is left unchanged). Every other
    OSError propagates unchanged. The temp file is removed in every case; a failed removal is ignored.
    """
    temp_name = _write_temp(dir_fd, text)
    try:
        os.link(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    finally:
        _unlink_quietly(dir_fd, temp_name)


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


def append_line(dir_fd, name, text):
    """Append text to `name` in the folder (created if needed) on an O_APPEND descriptor.

    Raises OSError for an entry that is not a regular file or a failed write.
    """
    file_fd = _open_regular_file(dir_fd, name, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        data = text.encode("utf-8")
        while data:
            data = data[os.write(file_fd, data):]
    finally:
        os.close(file_fd)


def append_lineage(dir_fd, successor, predecessor, predecessor_session, successor_session):
    """Record one handoff in the lineage file: the launcher writes it, the worktree cleanup reads it with read_lineage.

    Raises OSError like append_line.
    """
    line = json.dumps(
        {"successor": successor, "predecessor": predecessor, "time": time.time(),
         "predecessor_session": predecessor_session, "successor_session": successor_session}
    )
    append_line(dir_fd, LINEAGE_FILE, line + "\n")


def read_lineage(dir_fd):
    """{successor handle: predecessor handle} from the lineage file. None when the file is missing, unreadable, unsafe or
    malformed, or when a successor has two lines: all of these give no proof."""
    try:
        text = read_file(dir_fd, LINEAGE_FILE, LINEAGE_READ_BYTES)
    except (OSError, ValueError):
        return None
    if text is None:
        return None
    links = {}
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            return None
        if not isinstance(entry, dict):
            return None
        successor, predecessor = entry.get("successor"), entry.get("predecessor")
        if not all(isinstance(value, str) and value for value in (successor, predecessor)) or successor in links:
            return None
        links[successor] = predecessor
    return links


def read_file(dir_fd, name, limit=MAX_READ_BYTES):
    """Return the UTF-8 text of `name` in the folder, or None when it does not exist.

    Raises for a file that is not a regular file, is over `limit` bytes, or is not valid UTF-8.
    """
    try:
        file_fd = _open_regular_file(dir_fd, name, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        handle = os.fdopen(file_fd, "rb")
    except BaseException:
        _close_quietly(file_fd)
        raise
    with handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"{name} is over {limit} bytes")
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
