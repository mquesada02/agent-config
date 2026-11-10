#!/usr/bin/env python3
"""Structural assertion script for a ci-pipelines create run.

Usage: check_workflow.py WORKFLOW --assert NAME[=ARGS] [NAME[=ARGS] ...]

WORKFLOW is a path, or - for stdin. It is the text of a workflow, or of a Dependabot file for the `dependabot`
assertion. The script reads the text only (no YAML parser) and runs each assertion in the order given.
Assertions: name=<text> job=<id,...> no-job=<id,...> triggers concurrency permissions pinned-uses
persist-credentials pinned-runners no-run-expr named-run-steps short-run-blocks short-comments timeouts
timeout=<job>:<minutes> gate changes fail-fast matrix-node=<majors> matrix-only-test matrix-name no-shards
install=<command> audit-job no-privileged-trigger no-needs-between job-names affected-run=<turbo|nx|pnpm>
checkout-depth=default workers=1 text=<s> no-text=<s> dependabot security-audit.
Output: one line "FAIL <assertion>: <message>" for each failed assertion, then PASS or FAIL.
Exit code: 0 pass, 1 fail, 2 usage error, unknown assertion or unreadable file.
"""
import argparse
import re
import sys

HEAVY = ("lint", "typecheck", "test", "build")
CONCURRENCY = ("group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}",
               "cancel-in-progress: ${{ github.event_name == 'pull_request' }}")
FAIL_FAST = "fail-fast: ${{ github.event_name == 'pull_request' }}"
INSTALL = re.compile(r"^(npm (ci|install|i)(\s|$)|pnpm (install|i)(\s|$)|yarn(\s+install)?(\s+-.*)?$)")
AFFECTED = {
    "turbo": (r"turbo run {task} --affected(\s|$)", r"turbo run {task}(\s|$)"),
    "nx": (r"nx affected -t {task}(\s|$)", r"nx run-many -t {task}(\s|$)"),
    "pnpm": (r'pnpm --filter "\.\.\.\[origin/main\]" run {task}(\s|$)', r"pnpm -r run {task}(\s|$)"),
}


def top_block(lines, key):
    """The lines under a top-level key (without the key line), or None when the key is missing."""
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}:", line):
            body = []
            for nxt in lines[i + 1:]:
                if nxt.strip() and not nxt[0].isspace() and not nxt.startswith("#"):
                    break
                body.append(nxt)
            return body
    return None


def jobs_of(lines):
    """Job id to the lines of the job (its key line included), in file order."""
    body = top_block(lines, "jobs") or []
    result, current = {}, None
    for line in body:
        match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if match:
            current = match.group(1)
            result[current] = [line]
        elif current:
            result[current].append(line)
    return result


def steps_of(job):
    steps, in_steps = [], False
    for line in job:
        if re.match(r"^    steps:\s*$", line):
            in_steps = True
        elif in_steps and re.match(r"^      - ", line):
            steps.append([line])
        elif in_steps and steps:
            steps[-1].append(line)
    return steps


def unquote(value):
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value


def field(block, key, indents=("    ",)):
    """The value of a key at one of the given indents (a step key also matches `      - key:`)."""
    for line in block:
        for indent in indents:
            match = re.match(rf"^{indent}{re.escape(key)}:\s*(.*?)\s*$", line)
            if match:
                return unquote(match.group(1))
    return None


def step_field(step, key):
    return field(step, key, ("      - ", "        "))


def run_body(step):
    """The lines of the `run:` value of a step, or None when the step has no run."""
    for i, line in enumerate(step):
        match = re.match(r"^(?:      - |        )run:\s*(.*)$", line)
        if match:
            if match.group(1)[:1] in ("|", ">"):
                body = []
                for nxt in step[i + 1:]:
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= 8:
                        break
                    body.append(nxt)
                while body and not body[-1].strip():
                    body.pop()
                return body
            return [match.group(1)]
    return None


def run_lines(job):
    return [line.strip() for step in steps_of(job) for line in (run_body(step) or [])]


def needs_of(job):
    for i, line in enumerate(job):
        match = re.match(r"^    needs:\s*(.*)$", line)
        if match:
            value = match.group(1).strip()
            if value.startswith("["):
                return [item.strip().strip("'\"") for item in value.strip("[]").split(",") if item.strip()]
            if value:
                return [value.strip("'\"")]
            names = []
            for nxt in job[i + 1:]:
                item = re.match(r"^      - (\S+)", nxt)
                if not item:
                    break
                names.append(item.group(1))
            return names
    return []


def matrix_keys(job):
    keys, in_matrix = [], False
    for line in job:
        if re.match(r"^      matrix:\s*$", line):
            in_matrix = True
        elif in_matrix and (key := re.match(r"^        (\w+):", line)):
            keys.append(key.group(1))
        elif in_matrix and line.strip() and len(line) - len(line.lstrip()) <= 6:
            break
    return [key for key in keys if key not in ("include", "exclude")]


class Workflow:
    def __init__(self, text):
        self.text = text
        self.lines = text.splitlines()
        self.jobs = jobs_of(self.lines)

    def steps(self):
        return [step for job in self.jobs.values() for step in steps_of(job)]

    def uses(self):
        return [(m.group(1), (m.group(2) or "").strip()) for line in self.lines
                if (m := re.match(r"^\s*(?:- )?uses:\s*(\S+)\s*(?:#\s*(.*))?$", line))]


# Each assertion takes the workflow and its argument and returns a list of failure messages.
def a_name(wf, arg):
    match = re.search(r"(?m)^name:\s*(.*?)\s*$", wf.text)
    actual = match.group(1).strip("'\"") if match else None
    return [] if actual == arg else [f"top-level name is {actual!r}, expected {arg!r}"]


def a_job(wf, arg):
    return [f"job {job} is missing" for job in arg.split(",") if job not in wf.jobs]


def a_no_job(wf, arg):
    return [f"job {job} must not exist" for job in arg.split(",") if job in wf.jobs]


def a_triggers(wf, _):
    block = "\n".join(top_block(wf.lines, "on") or [])
    failures = []
    if not re.search(r"push:\s*\n\s+branches:\s*\[main\]", block):
        failures.append("push does not have `branches: [main]`")
    if "pull_request:" not in block:
        failures.append("pull_request is missing")
    if re.search(r"(?m)^\s+paths(-ignore)?:", block):
        failures.append("a workflow-level paths filter exists")
    return failures


def a_concurrency(wf, _):
    return [f"missing `{part}`" for part in CONCURRENCY if part not in wf.text]


def a_permissions(wf, _):
    block = top_block(wf.lines, "permissions")
    if block is None:
        return ["no top-level permissions block"]
    body = "\n".join(block)
    failures = [] if re.search(r"(?m)^  contents:\s*read\s*$", body) else ["top level lacks `contents: read`"]
    return failures + [f"top level grants a write scope: {line.strip()}" for line in block if line.strip().endswith(": write")]


def a_pinned_uses(wf, _):
    failures = []
    for value, comment in wf.uses():
        if value.startswith("./"):
            continue
        if not re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", value):
            failures.append(f"{value} is not pinned to a full SHA")
        elif not re.fullmatch(r"v\d+(\.\d+){0,2}", comment):
            failures.append(f"{value} has no bare version comment")
    return failures


def a_persist_credentials(wf, _):
    return ["a checkout lacks `persist-credentials: false`" for step in wf.steps()
            if any("actions/checkout@" in line for line in step)
            and not any(re.search(r"persist-credentials:\s*false\s*$", line) for line in step)]


def a_pinned_runners(wf, _):
    return [f"floating runner label: {line.strip()}" for line in wf.lines
            if re.match(r"^\s+(runs-on|os):", line) and "-latest" in line]


def a_no_run_expr(wf, _):
    return [f"`${{{{ }}}}` in a run block of job {job}" for job, lines in wf.jobs.items()
            if any("${{" in line for line in run_lines(lines))]


def a_named_run_steps(wf, _):
    failures = []
    for step in wf.steps():
        if run_body(step) is None:
            continue
        name = step_field(step, "name")
        if not name:
            failures.append("a run step has no name")
        elif len(name) > 50 or re.search(r"#\d+|\b[A-Z]{2,}-\d+\b|\bv\d+(\.\d+)+\b|\(", name):
            failures.append(f"step name {name!r} is over 50 characters or holds an id, a version or a reason")
    return failures


def a_short_run_blocks(wf, _):
    return [f"a run block of job {job} has {len(body)} lines" for job, lines in wf.jobs.items()
            for step in steps_of(lines) if (body := run_body(step)) and len(body) > 10]


def a_short_comments(wf, _):
    failures, count = [], 0
    for line in wf.lines + [""]:
        count = count + 1 if re.match(r"^\s*#", line) else 0
        if count == 4:
            failures.append("a comment is over 3 lines")
    return failures


def a_timeouts(wf, _):
    return [f"job {job} has no timeout-minutes" for job, lines in wf.jobs.items()
            if field(lines, "timeout-minutes") is None]


def a_timeout(wf, arg):
    job, _, minutes = arg.partition(":")
    if not job or not minutes.isdigit():
        raise ValueError("timeout takes <job>:<minutes>")
    actual = field(wf.jobs.get(job, []), "timeout-minutes")
    return [] if actual == minutes else [f"job {job} has timeout-minutes {actual}, expected {minutes}"]


def a_gate(wf, _):
    job = wf.jobs.get("ci-passed")
    if job is None:
        return ["job ci-passed is missing"]
    failures = []
    if field(job, "name") != "CI passed":
        failures.append("ci-passed name is not `CI passed`")
    if field(job, "if") != "always()":
        failures.append("ci-passed does not have `if: always()`")
    missing = sorted(set(wf.jobs) - {"ci-passed"} - set(needs_of(job)))
    return failures + ([f"ci-passed does not need {', '.join(missing)}"] if missing else [])


def a_changes(wf, _):
    job = wf.jobs.get("changes")
    if job is None:
        return ["job changes is missing"]
    failures = []
    if not any("dorny/paths-filter@" in line for line in job):
        failures.append("changes does not use dorny/paths-filter")
    if not any(re.match(r"^\s+pull-requests:\s*read\s*$", line) for line in job):
        failures.append("changes lacks `pull-requests: read`")
    for name in HEAVY:
        if name in wf.jobs:
            if "changes" not in needs_of(wf.jobs[name]):
                failures.append(f"{name} does not need changes")
            if field(wf.jobs[name], "if") != "needs.changes.outputs.code == 'true'":
                failures.append(f"{name} lacks the changes `if:`")
    return failures


def a_fail_fast(wf, _):
    return [f"job {job} has a matrix without `{FAIL_FAST}`" for job, lines in wf.jobs.items()
            if matrix_keys(lines) and FAIL_FAST not in "\n".join(lines)]


def a_matrix_node(wf, arg):
    job = wf.jobs.get("test", [])
    match = next((m for line in job if (m := re.match(r"^        node:\s*\[(.*)\]\s*$", line))), None)
    actual = [item.strip() for item in match.group(1).split(",")] if match else None
    expected = arg.split(",")
    if actual is not None and sorted(actual) == sorted(expected):
        return []
    return [f"test matrix node is {actual}, expected the majors {expected} in any order"]


def a_matrix_only_test(wf, _):
    return [f"job {job} has a matrix" for job, lines in wf.jobs.items() if job != "test" and matrix_keys(lines)]


def a_matrix_name(wf, _):
    job = wf.jobs.get("test", [])
    name = field(job, "name") or ""
    return [f"the test job name lacks ${{{{ matrix.{key} }}}}" for key in matrix_keys(job)
            if f"${{{{ matrix.{key} }}}}" not in name]


def a_no_shards(wf, _):
    return ["the workflow mentions a shard"] if "shard" in wf.text.lower() else []


def a_install(wf, arg):
    installs = [line for job in wf.jobs.values() for line in run_lines(job) if INSTALL.match(line)]
    if not installs:
        return ["no install step"]
    return [f"install command {line!r} is not {arg!r}" for line in installs if line != arg]


def a_audit_job(wf, _):
    job = wf.jobs.get("audit")
    if job is None:
        return ["job audit is missing"]
    failures = []
    runs = run_lines(job)
    if not any("--audit-level=high" in line for line in runs):
        failures.append("audit does not run with --audit-level=high")
    if "needs.changes.outputs.lockfile == 'true'" not in (field(job, "if") or ""):
        failures.append("audit does not wait for a lockfile change on PRs")
    if "audit" not in needs_of(wf.jobs.get("ci-passed", [])):
        failures.append("audit is not in the needs of the gate")
    failures += [f"job {name} runs an audit" for name, lines in wf.jobs.items() if name != "audit"
                 and any(re.search(r"\baudit\b", line) for line in run_lines(lines))]
    return failures


def a_no_privileged_trigger(wf, _):
    return [f"{word} is used" for word in ("pull_request_target", "workflow_run") if word in wf.text]


def a_no_needs_between(wf, _):
    return [f"{name} needs {', '.join(extra)}" for name in HEAVY if name in wf.jobs
            if (extra := sorted(set(needs_of(wf.jobs[name])) - {"changes"}))]


def a_job_names(wf, _):
    # A matrix label such as "(node ${{ matrix.node }}, shard ${{ matrix.shard }}/4)" (NAME-05) is not a task list.
    return [f"job {job} has the name {name!r} that lists tasks" for job, lines in wf.jobs.items()
            if (name := field(lines, "name"))
            and re.search(r",| and |&|/", re.sub(r"\([^()]*\$\{\{\s*matrix\.[^()]*\)", "", name))]


def a_affected_run(wf, arg):
    if arg not in AFFECTED:
        raise ValueError("affected-run takes turbo, nx or pnpm")
    failures = []
    for task in HEAVY:
        job = wf.jobs.get(task)
        if job is None:
            continue
        affected, full = (pattern.format(task=task) for pattern in AFFECTED[arg])
        steps = steps_of(job)
        pr = [s for s in steps if "pull_request" in (step_field(s, "if") or "")]
        push = [s for s in steps if "push" in (step_field(s, "if") or "")]
        if not any(re.search(affected, line) for s in pr for line in run_body(s) or []):
            failures.append(f"{task} has no affected-only step on a PR")
        if not any(re.search(full, line) and "--affected" not in line for s in push for line in run_body(s) or []):
            failures.append(f"{task} does not run every package on a push")
        if not any("fetch-depth: 0" in line for s in steps for line in s):
            failures.append(f"{task} checkout lacks fetch-depth: 0")
    if arg == "nx" and "nrwl/nx-set-shas@" not in wf.text:
        failures.append("nx affected needs nrwl/nx-set-shas")
    return failures


def a_checkout_depth(wf, arg):
    if arg != "default":
        raise ValueError("checkout-depth takes default")
    return ["a checkout has a fetch-depth key"] if "fetch-depth" in wf.text else []


def a_workers(wf, arg):
    if arg != "1":
        raise ValueError("workers takes 1")
    runs = [line for job in wf.jobs.values() for line in run_lines(job) if "playwright test" in line]
    if not runs:
        return ["no Playwright run"]
    return [f"Playwright run without --workers=1: {line}" for line in runs
            if not re.search(r"--workers=1(\s|$)", line)]


def a_text(wf, arg):
    return [] if arg in wf.text else [f"the text {arg!r} is missing"]


def a_no_text(wf, arg):
    return [f"the text {arg!r} is present"] if arg in wf.text else []


def a_dependabot(wf, _):
    checks = {
        "a github-actions entry": r"package-ecosystem:\s*[\"']?github-actions[\"']?\s*$",
        "directory /": r"directory:\s*[\"']?/[\"']?\s*$",
        "weekly interval": r"interval:\s*[\"']?weekly[\"']?\s*$",
    }
    # The three checks must hold on one entry of `updates:`. An entry starts at a list item of the first item's indent.
    # A line that is not a list item and is not indented deeper than the items ends the last entry.
    entries, indent, open_entry = [], None, False
    for line in wf.text.splitlines():
        item = re.match(r"^(\s*)- ", line)
        if item and indent is None:
            indent = len(item.group(1))
        if item and len(item.group(1)) == indent:
            entries.append([])
            open_entry = True
        elif open_entry and line.strip() and not line.lstrip().startswith("#") and len(line) - len(line.lstrip()) <= indent:
            open_entry = False
        if open_entry:
            entries[-1].append(line)
    texts = ["\n".join(lines) for lines in entries]
    candidates = [text for text in texts if re.search(checks["a github-actions entry"], text, re.M)]
    if not candidates:
        return ["no github-actions entry"]
    missing = [[what for what, pattern in checks.items() if not re.search(pattern, entry, re.M)]
               for entry in candidates]
    if [] in missing:
        return []
    return [f"the github-actions entry has no {what}" for what in min(missing, key=len)]


def a_security_audit(wf, _):
    failures = a_name(wf, "Security audit")
    code = "\n".join(line for line in wf.lines if not line.lstrip().startswith("#"))
    cron = re.search(r"(?m)^\s*schedule:\s*\n(?:\s+.*\n)*?\s+- cron:\s*['\"]?(\d+)\s", code + "\n")
    if not cron:
        failures.append("no schedule cron")
    elif int(cron.group(1)) % 2 == 0:
        failures.append("the cron minute is even")
    if not wf.jobs:
        failures.append("no job")
    audit = re.compile(r"\baudit\b.*--audit-level=high(\s|$)")
    if not any(audit.search(re.sub(r"\s+#.*$", "", line)) for job in wf.jobs.values() for line in run_lines(job)):
        failures.append("no audit command with --audit-level=high")
    for check in (a_permissions, a_timeouts, a_pinned_uses, a_persist_credentials):
        failures += check(wf, None)
    return failures


ASSERTIONS = {
    "name": (a_name, True), "job": (a_job, True), "no-job": (a_no_job, True), "triggers": (a_triggers, False),
    "concurrency": (a_concurrency, False), "permissions": (a_permissions, False),
    "pinned-uses": (a_pinned_uses, False), "persist-credentials": (a_persist_credentials, False),
    "pinned-runners": (a_pinned_runners, False), "no-run-expr": (a_no_run_expr, False),
    "named-run-steps": (a_named_run_steps, False), "short-run-blocks": (a_short_run_blocks, False),
    "short-comments": (a_short_comments, False), "timeouts": (a_timeouts, False), "timeout": (a_timeout, True),
    "gate": (a_gate, False), "changes": (a_changes, False), "fail-fast": (a_fail_fast, False),
    "matrix-node": (a_matrix_node, True), "matrix-only-test": (a_matrix_only_test, False),
    "matrix-name": (a_matrix_name, False), "no-shards": (a_no_shards, False), "install": (a_install, True),
    "audit-job": (a_audit_job, False), "no-privileged-trigger": (a_no_privileged_trigger, False),
    "no-needs-between": (a_no_needs_between, False), "job-names": (a_job_names, False),
    "affected-run": (a_affected_run, True), "checkout-depth": (a_checkout_depth, True),
    "workers": (a_workers, True), "text": (a_text, True), "no-text": (a_no_text, True),
    "dependabot": (a_dependabot, False), "security-audit": (a_security_audit, False),
}


def parse(spec):
    name, _, arg = spec.partition("=")
    if name not in ASSERTIONS:
        raise ValueError(f"unknown assertion {name!r}")
    function, needs_arg = ASSERTIONS[name]
    if needs_arg:
        if not arg:
            raise ValueError(f"{name} needs an argument ({name}=...)")
    elif arg:
        raise ValueError(f"{name} takes no argument")
    return name, function, arg


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workflow")
    parser.add_argument("--assert", dest="specs", nargs="+", required=True, metavar="NAME[=ARGS]")
    args = parser.parse_args(argv)
    try:
        checks = [parse(spec) for spec in args.specs]
        if args.workflow == "-":
            text = sys.stdin.buffer.read().decode("utf-8")
        else:
            with open(args.workflow, encoding="utf-8") as handle:
                text = handle.read()
    except (ValueError, OSError, UnicodeDecodeError) as error:
        print(f"check_workflow: {error}", file=sys.stderr)
        return 2
    wf = Workflow(text)
    out = []
    for name, function, arg in checks:
        try:
            messages = function(wf, arg)
        except ValueError as error:
            print(f"check_workflow: {error}", file=sys.stderr)
            return 2
        if messages:
            out.append(f"FAIL {name}: {'; '.join(messages)}")
    print("\n".join(out + ["FAIL" if out else "PASS"]))
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
