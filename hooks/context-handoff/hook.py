#!/usr/bin/env python3
# Context hook: at 80% of the model's context window it blocks the session with the handoff instruction, re-blocks an
# ignored instruction, and halts the session after 3 re-blocks. It runs on Stop and PostToolUse and must never break a
# session: any internal error gives no output and exit 0 (auto-compact stays the backstop).
#
# Two maintenance points:
# - MODEL_WINDOWS below: the fallback model -> window size table. Add a model here when it has a native 1M window.
# - CLAUDE_CODE_SESSION_ATTENDED: an undocumented variable. If Claude Code renames it, headless runs get the block too.
# The hook and launch.py share these literals without a shared module: the file names .launch and .manual, the word
# "started", the result status words, the successor marker being the predecessor's handoff path, and the 80% in the worker escalation text.
# Change them together.
import json
import math
import os
import shlex
import stat
import sys
import unicodedata

THRESHOLD_PERCENT = 80
REBLOCK_GRACE_CALLS = 10  # PostToolUse calls since the last block before the next re-block
MAX_REBLOCKS = 3
BASH_TIMEOUT_MS = 120000
CHUNK_BYTES = 256 * 1024
MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 4 * 1024 * 1024
ATTENDED_VARIABLE = "CLAUDE_CODE_SESSION_ATTENDED"
MARKER_VARIABLE = "CONTEXT_HANDOFF_SUCCESSOR"  # set by the launcher in the successor's start command: the predecessor's handoff path
HOOK_DIR = os.path.dirname(os.path.realpath(__file__))
LAUNCHER = os.path.join(HOOK_DIR, "launch.py")
# escalation-failed is emitted only by the worker launcher path; the plain and coordinator paths never emit it
STATUS_WORDS = ("ok", "failed", "escalation-failed", "manual")
HANDOFF_SUFFIX = ".handoff.md"
NO_RESULT_TEXT = "launcher gave no result; check Orca for a successor terminal before you start one"

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

# Text slots of the block instruction, one set per role; the hook logic does not depend on them.
STATE_CORE = """
   The State section has these fields, one per line:
   - session type: plain, worker or coordinator
   - cwd and worktree path
   - git branch
   - model, permission mode and effort: copy them from the command in step 4
   - predecessor session_id: {session_id}
   - predecessor transcript_path: {transcript_path}
   - predecessor Orca terminal handle, or none
   - links to the map, the spec and the ticket in progress
   - the review phase (CLAUDE.md section 6) and its round count
   Write unknown for a field that you do not know. Run no command to find it: step 1 allows no other Bash command."""
WORKER_STATE_BLOCK = """
   A worker adds these fields after the core fields, one per line, in this order:
   - the injected Orca preamble, copied exactly (terminal handle, Task ID, Dispatch ID, `ask` command, coordinator handle)
   - any ask that waits for an answer, with its message ID, or none
   Write unknown for a field of this list that you do not know; run no command to find it."""  # appended to the State fields, before the coordinator block
COORDINATOR_STATE_BLOCK = """
   A coordinator adds these fields after the core fields, one per line, in this order:
   - Run ID
   - active Dispatches, each with its Task ID, or none
   - unacked delivery IDs, each with every message in it, or none. Name each message by its Orca message ID, its sender and its subject, and mark it done or not done. The successor matches a message by its message ID, because the delivery IDs change at redelivery.
   - unanswered questions and escalations that wait for an answer, or none
   - the next CLAUDE.md section-7 step per ticket
   Write unknown for a field of this list that you do not know; run no command to find it."""  # appended to the State fields, after the worker block
SUCCESSOR_STEPS_INTRO = """
   Then copy these successor steps word for word into the handoff, under the heading "Successor steps":"""
SUCCESSOR_COMMON_STEPS = """
   Every role: check each Orca ID that you take from the handoff with Orca before you use it (`run-show`, `task-list`, `worker-show`). A worker does this after its new Dispatch arrives.
   Every role: if any takeover step fails, keep the old terminal open, tell the user what failed, and stop. The takeover is done when you have read the handoff (and, for a coordinator, bound the Run)."""
PLAIN_SUCCESSOR_STEPS = """
   Plain session only:
   1. Read the handoff.
   2. Check the old terminal handle that your first prompt names (the prompt wins over the handoff) with `terminal show --terminal <handle>`, then close that terminal. If your first prompt names no Orca terminal, tell the user to close the old session instead.
   3. Continue the work."""
COORDINATOR_SUCCESSOR_STEPS = """
   Coordinator (use these steps instead of the plain steps):
   1. Read the handoff. It holds the Run ID.
   2. Check the Run ID with `run-show --id <Run ID>`. Then bind the Run with `run-use --id <Run ID>`. This fences the predecessor: its `check --wait` ends with `consumer_fenced`, and its `task-create` and `worker-start` fail.
   3. Check the old terminal handle that your first prompt names (the prompt wins over the handoff) with `terminal show --terminal <handle>`, then close that terminal. If your first prompt names no Orca terminal, tell the user to close the old session instead.
   4. Run `check`. Unacked deliveries return under new delivery IDs. Check each Task and Dispatch ID from the handoff with `task-list` and `worker-show` before you act on it. If such a check fails, tell the user and do not act on that ID.
   5. Skip the messages that the handoff marks as done. Match them by message ID. Ack each delivery once all of its messages are done or handled."""  # appended after the plain steps
WORKER_SUCCESSOR_STEPS = """
   Worker (use these steps instead of the plain steps):
   1. Wait for the new Dispatch. It arrives soon. Do nothing else and set no timeout: the coordinator may be busy or handing over. (The prompt that starts you says the same.)
   2. When it arrives, check the Task ID and the new Dispatch ID of the new preamble with `worker-show --dispatch <new Dispatch ID>`, then read the handoff before you act on the Task. Use neither the old Dispatch ID nor the old terminal handle in any Orca call.
   3. Do the Task under the new preamble. An ask from the old Dispatch is closed. If the handoff names such an ask and you still need the answer, ask again under the new Dispatch.
   4. Send `worker_done` with the IDs from the new preamble.
   The coordinator's commands close the old terminal: a worker never closes it."""  # appended after the coordinator steps
PLAIN_ROLE_BLOCK = " For a plain session (not an Orca coordinator or worker), the role is `plain`."  # appended to step 4
COORDINATOR_ROLE_BLOCK = " For an Orca coordinator (a session that owns an Orca Run and dispatches workers on it), the role is `coordinator`."  # appended to step 4, after the plain block
WORKER_ROLE_BLOCK = (
    " For an Orca worker (a session that Orca dispatched under a Task, with an injected preamble), the role is `worker`: replace the word ROLE_SLOT with"
    " `worker` and then four more words copied from the preamble, in this order and each in single quotes: your own terminal handle (the `--from` value),"
    " the Task ID, the Dispatch ID, and your coordinator's terminal handle. If a value contains a single quote or a control character, do not run the command; tell the user."
)  # appended to step 4, after the coordinator block

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
    values = [LAUNCHER, session_id, runtime_dir.runtime_dir_path(), handoff, model, _text(data.get("permission_mode")), _text(effort_level), _text(data.get("cwd"))]
    return "python3 -I " + " ".join(shlex.quote(value) for value in values) + " ROLE_SLOT"


def _field(value):
    """A hook-input value for the instruction text: one line without control characters, else `unknown`."""
    if not isinstance(value, str) or value.splitlines() != [value] or any(unicodedata.category(char).startswith("C") for char in value):
        return "unknown"
    return value


def state_layout(data):
    core = STATE_CORE.format(session_id=_field(data.get("session_id")), transcript_path=_field(data.get("transcript_path")))
    steps = SUCCESSOR_COMMON_STEPS + PLAIN_SUCCESSOR_STEPS + COORDINATOR_SUCCESSOR_STEPS + WORKER_SUCCESSOR_STEPS
    return core + WORKER_STATE_BLOCK + COORDINATOR_STATE_BLOCK + SUCCESSOR_STEPS_INTRO + steps


def block(state, data):
    command, handoff = state["command"], state["handoff"]
    reason = "\n".join([
        f"The context is at {THRESHOLD_PERCENT}% of the window. Hand over to a successor session now. Follow these steps in order.",
        "1. Stop the current work. From now on the only allowed Orca CLI call is the coordinator's `ack` (step 2); the only other allowed command is the launcher (step 4).",
        "2. If you are an Orca coordinator, ack only the deliveries that you fully handled.",
        f"3. Run /mattpocock-skills:handoff. Write the handoff to exactly this path: {handoff} . Put the State section first.{state_layout(data)}",
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


def marker_manual_text(dir_fd, marker):
    """Return the manual file text next to the marker's handoff path, or None. The marker is read only inside the runtime folder."""
    try:
        if not os.path.isabs(marker):
            return None
        real = os.path.realpath(marker)
        if os.path.dirname(real) != os.path.realpath(runtime_dir.runtime_dir_path()) or not os.path.basename(real).endswith(HANDOFF_SUFFIX):
            return None
        marker_session = os.path.basename(real)[: -len(HANDOFF_SUFFIX)]
        if not runtime_dir.valid_session_id(marker_session):
            return None
        text = runtime_dir.read_file(dir_fd, marker_session + ".manual")
    except (OSError, ValueError):
        return None
    return (text or "").strip() or None


def loop_halt(state, dir_fd, percent, marker):
    text = f"handoff loop: context already at {percent}% after takeover"
    manual = marker_manual_text(dir_fd, marker)
    return halt(state, f"{text}; {manual}" if manual else text)


def check_threshold(dir_fd, data, session_id, state, first_event):
    window = read_window(dir_fd, session_id)
    measure = scan_transcript(data.get("transcript_path"))
    if measure is None:
        return None
    tokens, transcript_model = measure
    size, model = window if window else (model_window(transcript_model), transcript_model)
    if size is None or tokens * 100 < size * THRESHOLD_PERCENT:
        return None
    marker = os.environ.get(MARKER_VARIABLE)
    if marker and first_event:
        return loop_halt(state, dir_fd, tokens * 100 // size, marker)
    state["handoff"] = os.path.join(runtime_dir.runtime_dir_path(), session_id + HANDOFF_SUFFIX)
    state["command"] = launcher_command(data, session_id, state["handoff"], model)
    state.update(triggered=True, reblocks=0, calls_since_block=0)
    return block(state, data)


def halt(state, text):
    state["done"] = True
    return {"continue": False, "stopReason": text}


def is_launcher_call(data, session_id):
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if data.get("tool_name") != "Bash" or not isinstance(command, str):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return len(words) >= 4 and words[:3] == ["python3", "-I", LAUNCHER] and words[3] == session_id


def parse_result_line(line):
    """Return the text after the status word of a result line, or None."""
    word, _, text = line.strip().partition(" ")
    text = text.strip()
    return text if word in STATUS_WORDS and text else None


def nonblank_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def response_result(response):
    """Return the result text of a launcher call's tool_response, or None when it has no single parsable result line."""
    text = response.get("stdout") if isinstance(response, dict) else response
    lines = nonblank_lines(text) if isinstance(text, str) else []
    return parse_result_line(lines[0]) if len(lines) == 1 else None


def read_launch(dir_fd, session_id):
    """Return (shape, result text): A started only, B started and a result line, C other, D no file. An unreadable file raises."""
    text = runtime_dir.read_file(dir_fd, session_id + ".launch")
    if text is None:
        return "D", None
    lines = nonblank_lines(text)
    if lines == ["started"]:
        return "A", None
    result = parse_result_line(lines[1]) if len(lines) == 2 and lines[0] == "started" else None
    return ("B", result) if result else ("C", None)


def triggered_output(dir_fd, event, state, data, session_id):
    launcher_call = event == "PostToolUse" and is_launcher_call(data, session_id)
    result = response_result(data.get("tool_response")) if launcher_call else None
    shape = None
    if not result:
        try:
            shape, result = read_launch(dir_fd, session_id)
        except (OSError, ValueError):
            if not launcher_call:
                raise  # fail open: no output and no state write
            # unreadable launch file on a launcher call: no shape, so the no-result halt below
    if result:
        return halt(state, result)
    if launcher_call or shape in ("A", "C"):
        return halt(state, NO_RESULT_TEXT)
    if event == "PostToolUse":
        state["calls_since_block"] += 1
        if state["calls_since_block"] < REBLOCK_GRACE_CALLS:
            return None
    if state["reblocks"] < MAX_REBLOCKS:
        state["reblocks"] += 1
        state["calls_since_block"] = 0
        return block(state, data)
    return halt(state, f"handoff failed: no launcher call after {MAX_REBLOCKS} reminders; write the handoff, replace ROLE_SLOT, then run: {state['command']}")


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
    first_event = state["events"] == 0
    state["events"] += 1
    if state["triggered"]:
        output = triggered_output(dir_fd, data["hook_event_name"], state, data, session_id)
    else:
        output = check_threshold(dir_fd, data, session_id, state, first_event)
    runtime_dir.write_atomic(dir_fd, session_id + ".state", json.dumps(state))  # before any output; a failure gives no output
    if output:
        emit(output)


def run(data):
    global runtime_dir
    if not isinstance(data, dict) or data.get("hook_event_name") not in ("Stop", "PostToolUse"):
        return
    if "agent_id" in data or os.environ.get(ATTENDED_VARIABLE) == "0":
        return
    sys.path.insert(0, HOOK_DIR)
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
