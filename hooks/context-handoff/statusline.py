#!/usr/bin/env python3
# Status-line wrapper: saves the context-window size and the full model id for the context hook, then runs ccstatusline
# with the same stdin. The capture must never change what the status line shows: any capture error is swallowed.
import json
import math
import os
import subprocess
import sys


def _window_size(data):
    window = data.get("context_window")
    size = window.get("context_window_size") if isinstance(window, dict) else None
    if isinstance(size, bool) or not isinstance(size, (int, float)):
        return None
    if isinstance(size, float) and not (math.isfinite(size) and size.is_integer()):
        return None
    return int(size) if 1 <= size <= 2**53 else None


def capture(raw):
    # Imported here, inside the caller's guard, so a missing or broken shared module cannot stop the pass-through.
    sys.path.append(os.path.dirname(os.path.realpath(__file__)))
    import runtime_dir

    data = json.loads(raw)
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not runtime_dir.valid_session_id(session_id):
        return
    size = _window_size(data)
    model = data.get("model")
    model_id = model.get("id") if isinstance(model, dict) else None
    if size is None or not isinstance(model_id, str) or not model_id:
        return
    dir_fd = runtime_dir.open_runtime_dir()
    if dir_fd is None:
        return
    try:
        content = json.dumps({"context_window_size": size, "model_id": model_id})
        runtime_dir.write_atomic(dir_fd, session_id + ".window", content)
    finally:
        os.close(dir_fd)


def main():
    raw = sys.stdin.buffer.read()
    try:
        capture(raw)
    except Exception:
        pass
    try:
        child = subprocess.Popen(["ccstatusline"], stdin=subprocess.PIPE)
    except OSError as error:
        print(f"statusline.py: cannot run ccstatusline: {error}", file=sys.stderr)
        return 127 if isinstance(error, FileNotFoundError) else 126
    child.communicate(input=raw)  # ignores a broken pipe when the child closes stdin early
    return 128 - child.returncode if child.returncode < 0 else child.returncode


if __name__ == "__main__":
    sys.exit(main())
