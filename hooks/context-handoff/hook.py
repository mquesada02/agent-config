#!/usr/bin/env python3
# Context hook: at 80% of the model's context window it blocks the session with the handoff instruction, re-blocks an
# ignored instruction, and halts the session after 3 re-blocks. It runs on Stop and PostToolUse and must never break a
# session: any internal error gives no output and exit 0 (auto-compact stays the backstop).
#
# Two maintenance points:
# - MODEL_WINDOWS below: the fallback model -> window size table. Add a model here when it has a native 1M window.
# - CLAUDE_CODE_SESSION_ATTENDED: an undocumented variable. If Claude Code renames it, headless runs get the block too.
import json
import math
import os
import shlex
import stat
import sys

THRESHOLD_PERCENT = 80
REBLOCK_GRACE_CALLS = 10  # PostToolUse calls since the last block before the next re-block
MAX_REBLOCKS = 3
BASH_TIMEOUT_MS = 120000
CHUNK_BYTES = 256 * 1024
MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
ATTENDED_VARIABLE = "CLAUDE_CODE_SESSION_ATTENDED"
HOOK_DIR = os.path.dirname(os.path.realpath(__file__))

# Model-id prefixes with a native 1M window (Fable 5+, Sonnet 5+, Haiku 5.5, Opus 4.7+, per the Claude Code model list). A model id matches a prefix when it
# equals it or continues with "-". Only listed prefixes match, so a newer model must be added here. Models whose window
# depends on a "[1m]" suffix (4.6 era) stay out: the transcript model id has no suffix.
MODEL_WINDOWS = {
    "claude-fable-5": 1000000,
    "claude-sonnet-5": 1000000,
    "claude-opus-5": 1000000,
    "claude-haiku-5-5": 1000000,
    "claude-opus-4-7": 1000000,
}

# Open text slots of the block instruction. Later tickets fill them; the hook logic does not change.
STATE_LAYOUT_AND_SUCCESSOR_STEPS = ""  # appended to step 3
PLAIN_ROLE_BLOCK = ""  # appended to step 4
COORDINATOR_ROLE_BLOCK = ""  # appended to step 4, after the plain block
WORKER_ROLE_BLOCK = ""  # appended to step 4, after the coordinator block

runtime_dir = None  # imported inside run(), so a missing shared module fails open instead of crashing


def model_window(model):
    for prefix, size in MODEL_WINDOWS.items():
        if model == prefix or model.startswith(prefix + "-"):
            return size
    return None


def read_window(dir_fd, session_id):
    """Return (size, model_id) from the window file, or None when the file is absent or invalid."""
    try:
        text = runtime_dir.read_file(dir_fd, session_id + ".window")
        data = json.loads(text) if text is not None else None
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    size, model_id = data.get("context_window_size"), data.get("model_id")
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return None
    if isinstance(size, float) and not (math.isfinite(size) and size.is_integer()):
        return None
    if not (1 <= size <= 2**53) or not isinstance(model_id, str) or not model_id:
        return None
    return int(size), model_id


def _measure_line(line):
    """Return (tokens, model) when the transcript line is a qualifying assistant line, else None."""
    if b'"usage"' not in line:  # cheap prefilter: do not parse the large tool results; Claude Code writes the key unescaped
        return None
    try:
        entry = json.loads(line)
    except (ValueError, RecursionError, MemoryError):
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain") or entry.get("isApiErrorMessage"):
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    model, usage = message.get("model"), message.get("usage")
    if not isinstance(model, str) or not model or model == "<synthetic>" or not isinstance(usage, dict):
        return None
    counts = [usage[key] for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens") if key in usage]
    if not counts or any(isinstance(count, bool) or not isinstance(count, int) or count < 0 for count in counts):
        return None
    return sum(counts), model


def scan_transcript(path):
    """Return (tokens, model) of the last qualifying line, or None. An unreadable transcript gives None."""
    if not isinstance(path, str) or not path:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            return None
        with os.fdopen(fd, "rb") as handle:
            return _scan_backward(handle)
    except (OSError, ValueError):  # ValueError: a NUL byte in the path
        return None


def _scan_backward(handle):
    """Read the file backward in chunks, at most MAX_SCAN_BYTES, and return the first qualifying line's measure."""
    position = handle.seek(0, os.SEEK_END)
    carry = b""  # end part of a line whose start is in older data
    discarding = False  # inside a line over MAX_LINE_BYTES: drop its older bytes up to the next newline
    scanned = 0
    while position > 0 and scanned < MAX_SCAN_BYTES:
        size = min(CHUNK_BYTES, position)
        position -= size
        handle.seek(position)
        parts = (handle.read(size) + carry).split(b"\n")
        carry = b""
        scanned += size
        if discarding:
            if len(parts) == 1:
                continue
            parts.pop()  # the start part of the discarded line
            discarding = False
        if position > 0:
            carry = parts.pop(0)  # incomplete: its start is in older data
            if len(carry) > MAX_LINE_BYTES:
                carry, discarding = b"", True
        for line in reversed(parts):
            if line and len(line) <= MAX_LINE_BYTES:
                measure = _measure_line(line)
                if measure:
                    return measure
    return None


def _text(value):
    return value if isinstance(value, str) else ""


def launcher_command(data, session_id, handoff, model):
    effort = data.get("effort")
    effort_level = effort.get("level") if isinstance(effort, dict) else ""
    launcher = os.path.join(HOOK_DIR, "launch.py")
    values = [launcher, session_id, runtime_dir.runtime_dir_path(), handoff, model, _text(data.get("permission_mode")), _text(effort_level), _text(data.get("cwd"))]
    return "python3 -I " + " ".join(shlex.quote(value) for value in values) + " ROLE_SLOT"


def block(state):
    command, handoff = state["command"], state["handoff"]
    reason = "\n".join([
        f"The context is at {THRESHOLD_PERCENT}% of the window. Hand over to a successor session now. Follow these steps in order.",
        "1. Stop the current work. From now on the only allowed Orca CLI call is the coordinator's `ack` (step 2); the only other allowed command is the launcher (step 4).",
        "2. If you are an Orca coordinator, ack only the deliveries that you fully handled.",
        f"3. Run /mattpocock-skills:handoff. Write the handoff to exactly this path: {handoff} . Put the State section first.{STATE_LAYOUT_AND_SUCCESSOR_STEPS}",
        f"4. Run this command with the Bash tool, with a timeout of {BASH_TIMEOUT_MS} ms. First replace the word ROLE_SLOT as the role blocks say.{PLAIN_ROLE_BLOCK}{COORDINATOR_ROLE_BLOCK}{WORKER_ROLE_BLOCK}",
        command,
    ])
    return {"decision": "block", "reason": reason}


def load_state(dir_fd, session_id):
    state = {"events": 0, "triggered": False, "reblocks": 0, "calls_since_block": 0, "done": False, "command": "", "handoff": ""}
    text = runtime_dir.read_file(dir_fd, session_id + ".state")
    if text is None:
        return state
    loaded = json.loads(text)
    counts = ("events", "reblocks", "calls_since_block")
    valid = (
        isinstance(loaded, dict)
        and all(isinstance(loaded.get(key), int) and not isinstance(loaded.get(key), bool) and loaded[key] >= 0 for key in counts)
        and loaded["reblocks"] <= MAX_REBLOCKS
        and all(isinstance(loaded.get(key), bool) for key in ("triggered", "done"))
        and all(isinstance(loaded.get(key), str) for key in ("command", "handoff"))
        and (not loaded["triggered"] or (loaded["command"] and loaded["handoff"]))
    )
    if not valid:
        raise ValueError("invalid state file")
    return loaded  # unknown keys stay, so a later ticket can add fields


def check_threshold(dir_fd, data, session_id, state):
    window = read_window(dir_fd, session_id)
    measure = scan_transcript(data.get("transcript_path"))
    if measure is None:
        return None
    tokens, transcript_model = measure
    size, model = window if window else (model_window(transcript_model), transcript_model)
    if size is None or tokens * 100 < size * THRESHOLD_PERCENT:
        return None
    state["handoff"] = os.path.join(runtime_dir.runtime_dir_path(), session_id + ".handoff.md")
    state["command"] = launcher_command(data, session_id, state["handoff"], model)
    state.update(triggered=True, reblocks=0, calls_since_block=0)
    return block(state)


def triggered_output(event, state):
    if event == "PostToolUse":
        state["calls_since_block"] += 1
        if state["calls_since_block"] < REBLOCK_GRACE_CALLS:
            return None
    if state["reblocks"] < MAX_REBLOCKS:
        state["reblocks"] += 1
        state["calls_since_block"] = 0
        return block(state)
    state["done"] = True
    text = f"handoff failed: no launcher call after {MAX_REBLOCKS} reminders; write the handoff, replace ROLE_SLOT, then run: {state['command']}"
    return {"continue": False, "stopReason": text}


def emit(output):
    try:
        sys.stdout.write(json.dumps(output))
        sys.stdout.flush()
    except OSError:
        # The reader closed the pipe. Point stdout at /dev/null so the unflushed buffer cannot fail again at shutdown (exit code 120).
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)


def handle_event(dir_fd, data, session_id):
    state = load_state(dir_fd, session_id)
    if state["done"]:
        return
    state["events"] += 1
    if state["triggered"]:
        output = triggered_output(data["hook_event_name"], state)
    else:
        output = check_threshold(dir_fd, data, session_id, state)
    runtime_dir.write_atomic(dir_fd, session_id + ".state", json.dumps(state))  # before any output; a failure gives no output
    if output:
        emit(output)


def run(data):
    global runtime_dir
    if not isinstance(data, dict) or data.get("hook_event_name") not in ("Stop", "PostToolUse"):
        return
    if "agent_id" in data or os.environ.get(ATTENDED_VARIABLE) == "0":
        return
    sys.path.append(HOOK_DIR)
    import runtime_dir as module

    runtime_dir = module
    session_id = data.get("session_id")
    if not runtime_dir.valid_session_id(session_id):
        return
    dir_fd = runtime_dir.open_runtime_dir()
    if dir_fd is None:
        return
    try:
        lock_fd = runtime_dir.lock_file(dir_fd, session_id + ".lock")
        try:
            handle_event(dir_fd, data, session_id)
        finally:
            os.close(lock_fd)
    finally:
        os.close(dir_fd)


def main():
    try:
        run(json.loads(sys.stdin.buffer.read()))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
