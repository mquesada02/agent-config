"""The ownership and state checks that `cleanup` and `list-owned` share. Standard library only."""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "context-handoff"))
import runtime_dir  # noqa: E402  (the shared runtime folder of the context-handoff scripts)

REMOTE = "origin"
SKIP_COMMAND = "! ~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership {path}"
LINEAGE_MAX_STEPS = 20


def run(*command, cwd=None):
    try:
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except OSError as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def git(repo, *args):
    return run("git", "-C", repo, *args)


def failure_text(result):
    lines = (result.stderr or result.stdout or f"exit {result.returncode}").strip().splitlines()
    return lines[-1] if lines else "failed"


def read_json(result):
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data if isinstance(data, (dict, list)) else None


def anchor_worktree(handle):
    if not handle:
        return None
    shown = read_json(run("orca", "terminal", "show", "--terminal", handle, "--json"))
    try:
        return shown["result"]["terminal"]["worktreeId"] or None
    except (KeyError, TypeError):
        return None


def read_lineage():
    """{successor handle: predecessor handle} from the lineage file. None when the file is missing, unreadable, unsafe or
    malformed, or when a successor has two lines: all of these give no proof."""
    dir_fd = runtime_dir.open_runtime_dir()
    if dir_fd is None:
        return None
    try:
        return runtime_dir.read_lineage(dir_fd)
    finally:
        os.close(dir_fd)


def in_predecessor_chain(creator, handle):
    """True when `creator` is `handle` or a predecessor of it. No proof past 20 steps or at a repeated handle."""
    links = read_lineage()
    if links is None:
        return False
    seen = {handle}
    current = handle
    for _step in range(LINEAGE_MAX_STEPS + 1):
        if current == creator:
            return True
        current = links.get(current)
        if current is None or current in seen:
            return False
        seen.add(current)
    return False


def ownership_reason(record, anchor, handle):
    """Why this session owns the worktree, as a short text, or None when no proof holds."""
    provenance = record.get("cliProvenance")
    caller = provenance.get("callerTerminalHandle") if isinstance(provenance, dict) else None
    if anchor and anchor == record.get("id"):
        return "own worktree"
    if anchor and anchor == record.get("parentWorktreeId"):
        return "parent anchor"
    if handle and caller == handle:
        return "own handle"
    if handle and caller and in_predecessor_chain(caller, handle):
        return "predecessor chain"
    return None


def check_ownership(record, anchor, handle):
    if ownership_reason(record, anchor, handle):
        return []
    return ["Ownership: no proof that this session owns the worktree"]


def worker_rows(run_id):
    """Every row of `worker-list` for the Run, all pages. None when the list is not read in full."""
    rows = []
    cursor = ()
    while True:
        listed = read_json(run("orca", "orchestration", "worker-list", "--run", run_id, "--limit", "100", "--json", "--full", *cursor))
        result = listed.get("result") if isinstance(listed, dict) and listed.get("ok") is True else None
        workers = result.get("workers") if isinstance(result, dict) else None
        page = result.get("page") if isinstance(result, dict) else None
        if not isinstance(workers, list) or not isinstance(page, dict):
            return None
        rows += workers
        if page.get("hasMore") is False:
            return rows
        if page.get("hasMore") is not True or not page.get("nextCursor"):
            return None
        cursor = ("--cursor", page["nextCursor"])


def row_worktree(row):
    """The Orca worktree id of a Dispatch row: `resource.worktreeId`, or the projection when `resource` is null."""
    resource = row.get("resource")
    if resource is None:
        projection = row.get("projection")
        workspace = projection.get("workspace") if isinstance(projection, dict) else None
        return workspace.get("id") if isinstance(workspace, dict) else None
    return resource.get("worktreeId") if isinstance(resource, dict) else None


def bound_run():
    """(run id, rows) of the Run that Orca binds to this terminal. (None, None) when no Run is bound.
    The rows are None when the worker list is not read in full; an empty list is a full read."""
    current = read_json(run("orca", "orchestration", "run-current", "--json", "--full"))
    try:
        run_id = current["result"]["run"]["id"] if current["ok"] is True else None
    except (KeyError, TypeError):
        return None, None
    if not isinstance(run_id, str) or not run_id:
        return None, None
    rows = worker_rows(run_id)
    return run_id, None if rows is None else [row for row in rows if isinstance(row, dict)]


def run_proof(worktree_id, handle, rows):
    """The Run proof: the target is the worktree of a Dispatch of the bound Run, and this terminal is no worker of the Run."""
    if not handle or rows is None:
        return False
    if any(row.get("agentTerminalHandle") == handle for row in rows):
        return False
    return any(row_worktree(row) == worktree_id for row in rows)


def check_clean(target):
    status = git(target, "status", "--porcelain")
    if status.returncode != 0:
        return [f"Clean: git status failed: {failure_text(status)}"]
    if status.stdout.strip():
        return ["Clean: the worktree has uncommitted or untracked changes"]
    return []


def remote_ref_sha(target, ref):
    """Return (sha, error). The sha is None when the ref is absent on the remote."""
    result = git(target, "ls-remote", REMOTE, ref)
    if result.returncode != 0:
        return None, failure_text(result)
    for line in result.stdout.splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            return sha, None
    return None, None


def check_docker(target):
    """Check 8: no compose stack has a config file inside the target. No `docker` on PATH passes."""
    if shutil.which("docker") is None:
        return []
    result = run("docker", "compose", "ls", "-a", "--format", "json")
    stacks = read_json(result)
    if not isinstance(stacks, list):
        return [f"Docker: docker compose ls -a did not give a list of stacks: {failure_text(result)}"]
    reasons = []
    for stack in stacks:
        files = stack.get("ConfigFiles") if isinstance(stack, dict) else None
        if not isinstance(files, str):
            continue
        # ConfigFiles is comma-separated, so a path that holds a comma is not recognised (a limit of that field).
        paths = [os.path.realpath(path) for path in files.split(",") if os.path.isabs(path)]
        if any(path == target or path.startswith(target + os.sep) for path in paths):
            reasons.append(f"Docker: stack {stack.get('Name') or '(unnamed)'} has a config file in the worktree")
    return reasons
