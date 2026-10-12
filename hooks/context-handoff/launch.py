#!/usr/bin/env python3
# Launcher: the model runs it when the context hook blocks a session at 80%. It starts the successor session in a new
# Orca terminal in the same worktree, proves that the successor is alive, sends it the prompt, and prints exactly one
# result line ("<status word> <user text>") for the hook. It always exits 0 and writes nothing to stderr.
#
# Arguments: session_id runtime_dir handoff model permission_mode effort cwd role
# The role worker adds four more: worker_handle task_id dispatch_id coordinator_handle.
# The plain and coordinator roles share one path. The worker role follows the same path, checks its Dispatch with worker-show
# first, and sends an escalation to the coordinator after the successor has taken its prompt.
import json
import math
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata

OVERALL_SECONDS = 100  # inside the 120 s Bash timeout of the block instruction
WORK_SECONDS = 85  # work deadline; the rest of the overall time is the cleanup reserve
CALL_SECONDS = 10  # own limit of each status, list, show, create, send and close call
WAIT_SECONDS = 60  # own limit of the idle wait
MIN_CALL_SECONDS = 3  # a work call starts only when at least this much time is left
ERROR_CHARS = 300
TITLE_CHARS = 200
MAX_OUTPUT_BYTES = 1024 * 1024
CLI_FALLBACK = "orca-ide"  # never bare `orca` outside an Orca terminal: there it starts the GNOME screen reader

LINE_SEPARATORS = "  "
ARGUMENT_NAMES = ("session_id", "runtime_dir", "handoff", "model", "permission_mode", "effort", "cwd", "role")
WORKER_ARGUMENT_NAMES = ("worker_handle", "task_id", "dispatch_id", "coordinator_handle")
ROLES = ("plain", "coordinator", "worker")
FLAG_NAMES = ("--model", "--permission-mode", "--effort")
VALUE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]*")
HANDLE_PATTERN = re.compile(r"[A-Za-z0-9_.:][A-Za-z0-9_.:-]*")
TITLE_NUMBER_PATTERN = re.compile(r"(.*) ↻([0-9]{1,6})", re.DOTALL)

# Successor prompts (the text the user approved).
PROMPT_WITH_HANDLE = "Read {handoff} and follow it. You are the successor of Orca terminal {handle}. Close that terminal only after your takeover is done."
PROMPT_WITHOUT_HANDLE = "Read {handoff} and follow it. The session you replace did not run in an Orca terminal. When your takeover is done, tell the user to close the old session."
WORKER_PROMPT = "You are a worker successor. Wait. An Orca dispatch arrives soon. When it does, read {handoff} before you act on it."

STRAY_NOTE = "a terminal may have been created; check Orca for a stray terminal and close it"

runtime_dir = None  # imported inside attempt(), so a missing shared module gives one `failed` line instead of a traceback


class Reply:
    """The outcome of one Orca call: ok is True only for a parsed JSON body with `ok: true`."""

    def __init__(self, ok, data, error):
        self.ok, self.data, self.error = ok, data, one_line(error)

    def get(self, *keys):
        """The value at keys in the JSON body of a successful call, else None."""
        return dig(self.data, *keys) if self.ok else None


def dig(value, *keys):
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def clean(text):
    return "".join(" " if unicodedata.category(char).startswith("C") or char in LINE_SEPARATORS else char for char in text)


def one_line(text, limit=ERROR_CHARS):
    return " ".join(clean(text).split())[:limit]


def valid_handle(handle):
    return isinstance(handle, str) and HANDLE_PATTERN.fullmatch(handle) is not None


def check_arguments(argv):
    """Return the reason the arguments are invalid, or None. The reason names an argument, never its value."""
    base = len(ARGUMENT_NAMES)
    worker = len(argv) >= base and argv[base - 1] == "worker"
    names = ARGUMENT_NAMES + WORKER_ARGUMENT_NAMES if worker else ARGUMENT_NAMES
    if len(argv) != len(names):
        return f"expected {len(names)} arguments"
    session, folder, handoff, model, mode, effort, cwd, _role = argv[:base]
    for name, value in zip(names, argv):
        if clean(value) != value:
            return f"{name} has a control character"
    for name, value in zip(WORKER_ARGUMENT_NAMES, argv[base:]):
        if not valid_handle(value):
            return f"{name} is not valid"
    if not runtime_dir.valid_session_id(session):
        return "session_id is not valid"
    for name, path in (("runtime_dir", folder), ("handoff", handoff), ("cwd", cwd)):
        if not os.path.isabs(path):
            return f"{name} is not an absolute path"
    for name, value in (("model", model), ("permission_mode", mode), ("effort", effort)):
        if value and not VALUE_PATTERN.fullmatch(value):
            return f"{name} has a character that is not allowed"
    if os.path.normpath(folder) != folder or os.path.basename(folder) != runtime_dir.FOLDER_NAME:
        return "runtime_dir is not the runtime folder"
    if handoff != os.path.join(folder, session + ".handoff.md"):
        return "handoff is not the handoff file of the session"
    return None


def claude_arguments(model, mode, effort):
    arguments = ["claude"]
    for flag, value in zip(FLAG_NAMES, (model, mode, effort)):
        if value:
            arguments += [flag, value]
    return arguments


def managed_worktree(listing, cwd):
    """Return the listed path of the worktree that contains cwd, or None."""
    rows = listing.get("result", "worktrees")
    if not isinstance(rows, list):
        return None
    truncated = listing.get("result", "truncated") is not False  # missing or not a boolean counts as truncated
    target = os.path.realpath(cwd)
    best = None
    for row in rows:
        path = dig(row, "path")
        if not isinstance(path, str) or not os.path.isabs(path):
            continue
        if row.get("isArchived") is True or row.get("isBare") is True or row.get("hostId") != "local":
            continue
        real = os.path.realpath(path)
        inside = target == real or (not truncated and target.startswith(real.rstrip("/") + "/"))  # by path component
        if inside and (best is None or len(real) > len(best[0])):
            best = (real, path)
    return best[1] if best else None


def successor_title(title):
    """Return the successor's terminal title for a predecessor title: the base plus ` ↻<n>`."""
    title = clean(title)
    if len(title) > 1 and unicodedata.category(title[0]) == "So" and title[1].isspace():  # Claude Code's status glyph
        title = title[1:].lstrip()
    title = title.rstrip()
    match = TITLE_NUMBER_PATTERN.fullmatch(title)
    base, number = (match.group(1), int(match.group(2)) + 1) if match else (title, 1)
    base = base[:TITLE_CHARS].lstrip()
    return f"{base} ↻{number}" if base else "claude ↻1"


class Launch:
    def __init__(self, argv, start, dir_fd):
        self.dir_fd = dir_fd
        self.session, self.folder, self.handoff, self.model, self.mode, self.effort, self.cwd, self.role = argv[: len(ARGUMENT_NAMES)]
        self.worker = self.role == "worker"
        if self.worker:
            self.worker_handle, self.task, self.dispatch, self.coordinator = argv[len(ARGUMENT_NAMES):]
        self.claude = claude_arguments(self.model, self.mode, self.effort)
        self.work_end = start + WORK_SECONDS
        self.total_end = start + OVERALL_SECONDS
        old_handle = os.environ.get("ORCA_TERMINAL_HANDLE", "")
        self.old_handle = old_handle if valid_handle(old_handle) else ""
        self.cli = None
        self.created = None  # the handle of the terminal this launcher created, until the prompt is confirmed
        self.successor = None  # the handle of the successor, from the confirmed prompt on
        self.worktree = self.cwd  # the Orca worktree path for the coordinator commands; the cwd until the worktree is known
        self.manual = None

    def call(self, arguments, limit=CALL_SECONDS, until=None, minimum=MIN_CALL_SECONDS):
        """Run one Orca CLI call. `arguments` may be a function of the granted seconds. Never raises for a call problem."""
        seconds = min(limit, (until or self.work_end) - time.monotonic())
        if seconds < minimum or seconds <= 0:  # the close passes minimum 0 and still needs some time left
            return Reply(False, None, "the Orca call timed out")  # no time left: counts as a timeout without a call
        if callable(arguments):
            arguments = arguments(seconds)
        with tempfile.TemporaryFile() as output:  # a file, not a pipe: a grandchild cannot hold it open; an OSError here goes to the catch-all
            try:
                process = subprocess.Popen(
                    self.cli + arguments + ["--json"], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, start_new_session=True
                )
            except OSError as error:
                return Reply(False, None, f"cannot run {self.cli[0]}: {error.strerror or error}")
            try:
                process.wait(timeout=seconds)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
            if timed_out:
                return Reply(False, None, "the Orca call timed out")
            output.seek(0)
            raw = output.read(MAX_OUTPUT_BYTES + 1)
        if len(raw) > MAX_OUTPUT_BYTES:
            return Reply(False, None, "the Orca call gave too much output")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            data = None
        if not isinstance(data, dict):
            return Reply(False, None, "the Orca call gave no JSON: " + one_line(raw[:400].decode("utf-8", "replace"), 100))
        if data.get("ok") is True:
            return Reply(True, data, "")
        message = dig(data, "error", "message")
        return Reply(False, data, message if isinstance(message, str) and message else "the Orca call failed")

    def prompt(self):
        # Manual commands always use the without-handle prompt (user decision), so only the Orca start uses the handle.
        if self.worker:
            return self.prompt_without_handle()
        return PROMPT_WITH_HANDLE.format(handoff=self.handoff, handle=self.old_handle) if self.old_handle else self.prompt_without_handle()

    def prompt_without_handle(self):
        if self.worker:
            return WORKER_PROMPT.format(handoff=self.handoff)  # a worker successor waits for its Dispatch; it has no old handle to close
        return PROMPT_WITHOUT_HANDLE.format(handoff=self.handoff)

    def coordinator_commands(self, successor):
        """The one-line text of the exact commands that replace the worker. `successor` is the handle, or the placeholder text."""
        cli = shlex.join(self.cli or [CLI_FALLBACK])
        new = shlex.quote(successor) if valid_handle(successor) else successor  # the placeholder is inserted unquoted
        stop = f"{cli} orchestration worker-stop --dispatch {shlex.quote(self.dispatch)}"
        abandon = f"{cli} orchestration worker-abandon --dispatch {shlex.quote(self.dispatch)}"
        close = f"{cli} terminal close --terminal {shlex.quote(self.worker_handle)}"
        start = (
            f"{cli} orchestration worker-start --task {shlex.quote(self.task)} --retry-of {shlex.quote(self.dispatch)}"
            f" --worktree {shlex.quote('path:' + self.worktree)} --terminal {new}"
        )
        return clean(f"1) {stop}; 2) if step 1 returns stop_unknown (the worker ran on a reused terminal): {abandon}, then {close}; 3) {start}")

    def manual_text(self):
        command = "cd " + shlex.quote(self.cwd) + " && " + shlex.join(self.claude + [self.prompt_without_handle()])
        if not self.worker:
            return f"the handoff file is at {self.handoff}; start the successor with {command}"
        return (
            f"the handoff file is at {self.handoff}; start the successor with {command} in an Orca terminal of the worktree"
            f" (its handle is the value of $ORCA_TERMINAL_HANDLE there); then tell coordinator {self.coordinator}: {self.coordinator_commands('<new handle>')}"
        )

    def write_manual(self):
        """Write the manual file. Returns the failure (status word, text) or None."""
        manual = self.manual_text()
        try:
            runtime_dir.write_atomic(self.dir_fd, self.session + ".manual", manual)
        except OSError:
            return self.failed("cannot write the manual file")
        self.manual = manual
        return None

    def early_failed(self, error):
        """A worker failure before its IDs are verified: no manual part and no commands, only the handoff path."""
        return "failed", f"successor failed: {error}; the handoff file is at {self.handoff}"

    def failed(self, error, note=None):
        parts = ["successor failed: " + error]
        if self.manual:
            parts.append(self.manual)
        if note:
            parts.append(note)
        return "failed", "; ".join(parts)

    def close_created(self):
        """Close the terminal this launcher created. Returns the note for the user when the close failed, else None."""
        handle, self.created = self.created, None
        try:
            closed = self.call(["terminal", "close", "--terminal", handle], until=self.total_end, minimum=0).ok
        except Exception:  # the catch-all runs this too, so a failing close must not end the run without the note
            closed = False
        return None if closed else f"terminal {handle} may still run; close it before you start the manual command"

    def resolve_cli(self):
        """Return the Orca CLI command; an empty list when ORCA_CLI_COMMAND is set but cannot be split into a command."""
        command = os.environ.get("ORCA_CLI_COMMAND", "")
        if not command:
            return ["orca" if self.old_handle else CLI_FALLBACK]
        try:
            return shlex.split(command)
        except ValueError:
            return []

    def worktree_path(self):
        """Return the listed path of the Orca worktree that contains the cwd, or None when Orca is not running or does not manage it."""
        status = self.call(["status"])
        if not (status.get("result", "app", "running") is True and status.get("result", "runtime", "reachable") is True):
            return None
        return managed_worktree(self.call(["worktree", "list", "--limit", "1000"]), self.cwd)

    def title(self):
        shown = self.call(["terminal", "show", "--terminal", self.old_handle]) if self.old_handle else None
        title = shown.get("result", "terminal", "title") if shown else None
        return successor_title(title if isinstance(title, str) else "claude")

    def check_dispatch(self, worktree):
        """The worker pre-check: worker-show confirms the Dispatch, Task and worker handle. Writes the worker manual file. Returns the failure or None."""
        shown = self.call(["orchestration", "worker-show", "--dispatch", self.dispatch])
        if not shown.ok:
            return self.early_failed(shown.error)
        if (shown.get("result", "dispatch", "id"), shown.get("result", "dispatch", "taskId"), shown.get("result", "dispatch", "assigneeHandle")) != (
            self.dispatch, self.task, self.worker_handle
        ):
            return self.early_failed("the Dispatch does not match the worker handle and Task")
        if clean(worktree) != worktree:  # the path is printed into the commands
            return self.early_failed("worktree path has a control character")
        self.worktree = worktree
        return self.write_manual()

    def execute(self):
        """Steps 4 to 13. Returns (status word, user text)."""
        if self.role not in ROLES:
            return self.failed(f"role {self.role[:ERROR_CHARS]} is not supported")  # only the role value is cut
        if self.worker and self.old_handle != self.worker_handle:  # a missing or invalid variable counts as a mismatch
            return self.early_failed("worker handle is not this terminal")
        try:
            info = os.lstat(self.session + ".handoff.md", dir_fd=self.dir_fd)
            usable = stat.S_ISREG(info.st_mode) and info.st_size > 0
        except OSError:
            usable = False
        if not usable:
            return self.failed("the handoff file is missing or empty")
        self.cli = self.resolve_cli()
        if not self.worker:  # a worker writes its manual file only after worker-show: until then its IDs are only what the model typed
            failure = self.write_manual()
            if failure:
                return failure
        if not self.cli:
            return self.early_failed("ORCA_CLI_COMMAND is invalid") if self.worker else self.failed("ORCA_CLI_COMMAND is invalid")
        worktree = self.worktree_path()
        if worktree is None:
            failure = self.write_manual() if self.worker else None  # nothing can be verified without Orca: the text uses the unverified IDs
            return failure or ("manual", "no Orca: " + self.manual)
        if self.worker:
            failure = self.check_dispatch(worktree)
            if failure:
                return failure

        # No CLAUDE_CODE_DISABLE_TERMINAL_TITLE here (thirteenth amendment on #8): Orca reads Claude's title mark for idle detection, so the variable
        # breaks the tui-idle wait and worker-start --terminal after the successor's first turn. The ↻<n> title therefore lasts until that turn.
        start_command = "env CONTEXT_HANDOFF_SUCCESSOR=" + shlex.quote(self.handoff) + " " + shlex.join(self.claude)
        created = self.call(["terminal", "create", "--worktree", "path:" + worktree, "--title=" + self.title(), "--command", start_command])
        handle = created.get("result", "terminal", "handle")
        if not valid_handle(handle):
            return self.failed(created.error if not created.ok else "create gave no usable terminal handle", STRAY_NOTE)
        self.created = handle

        idle = self.call(
            lambda seconds: ["terminal", "wait", "--terminal", handle, "--for", "tui-idle", "--timeout-ms", str(int((seconds - 1) * 1000))], limit=WAIT_SECONDS
        )
        if idle.get("result", "wait", "satisfied") is not True:
            return self.failed(idle.error if not idle.ok else "the successor did not reach an idle prompt", self.close_created())
        sent = self.call(
            lambda seconds: ["terminal", "send", "--terminal", handle, "--text", self.prompt(), "--enter", "--wait-submit", str(math.floor(seconds - 2))]
        )
        stages = sent.get("result", "send", "prompt", "stages")
        if not (isinstance(stages, list) and "turn_started" in stages):
            return self.failed(sent.error if not sent.ok else "the successor did not take the prompt", self.close_created())
        self.created = None
        self.successor = handle
        if self.worker:
            return self.escalate()
        return "ok", f"context handoff done: successor {handle}"

    def escalate(self):
        """Send the escalation from the worker's own terminal, without --to: it goes to the Run mailbox, which survives a coordinator handover."""
        body = (
            f"Worker {self.worker_handle} (Task {self.task}, Dispatch {self.dispatch}) reached 80% of its context. Its successor {self.successor}"
            f" waits in terminal {self.successor} for a dispatch; the handoff file is at {self.handoff}."
            f" For coordinator {self.coordinator}, run: {self.coordinator_commands(self.successor)}"
        )
        sent = self.call(
            [
                "orchestration", "send", "--from", self.worker_handle, "--type", "escalation", "--subject", f"Worker handover: successor {self.successor}",
                "--body", clean(body), "--task-id", self.task, "--dispatch-id", self.dispatch,
            ]
        )
        return ("ok", f"context handoff done: successor {self.successor}") if sent.ok else self.escalation_failed()

    def escalation_failed(self):
        return "escalation-failed", (
            f"successor {self.successor} waits; tell the coordinator: {self.coordinator_commands(self.successor)};"
            " the coordinator may already have the escalation, so check its inbox before you run them"
        )

    def run(self):
        """Steps 3 to 13 with the launch file. Never raises."""
        try:
            runtime_dir.write_atomic(self.dir_fd, self.session + ".launch", "started\n")
        except OSError:
            return self.failed("cannot write the launch file")
        try:
            result = self.execute()
        except Exception as error:
            if self.worker and self.successor:  # the prompt is confirmed: the live successor must not be orphaned
                result = self.escalation_failed()
            else:
                note = self.close_created() if self.created else None
                result = self.failed(one_line(str(error) or type(error).__name__), note)
        try:
            runtime_dir.write_atomic(self.dir_fd, self.session + ".launch", "started\n" + result[0] + " " + result[1] + "\n")
        except OSError:
            pass  # the printed line wins; the hook reads it first
        return result


def attempt(argv, start):
    global runtime_dir
    sys.path.append(os.path.dirname(os.path.realpath(__file__)))
    import runtime_dir as module

    runtime_dir = module
    problem = check_arguments(argv)
    if problem:
        return "failed", "successor failed: invalid arguments: " + problem
    dir_fd = runtime_dir.open_runtime_dir(argv[1])
    if dir_fd is None:
        return "failed", "successor failed: runtime folder is not safe"
    try:
        return Launch(argv, start, dir_fd).run()
    finally:
        os.close(dir_fd)


def emit(status, text):
    data = f"{status} {text}\n".encode("utf-8", "replace")
    try:
        while data:
            data = data[os.write(1, data):]
    except OSError:
        pass  # the reader closed the pipe; the exit code stays 0


def main():
    start = time.monotonic()
    try:
        status, text = attempt(sys.argv[1:], start)
    except Exception as error:
        status, text = "failed", "successor failed: " + one_line(str(error) or type(error).__name__)
    emit(status, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
