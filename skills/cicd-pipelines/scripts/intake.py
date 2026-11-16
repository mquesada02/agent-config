#!/usr/bin/env python3
"""Print the repo facts of the cicd-pipelines skill as one JSON object.

Usage: intake.py REPO_PATH

Standard library only, plus `gh` and `git` as subprocesses. Every `gh` call is a read-only
`gh api <path>` call. Each fact is {"value", "status", "source"}; status is "detected",
"default" or "unknown". The script exits 0 when facts are unknown, and 2 on a usage error.

Environment: CICD_PIPELINES_NODE_SCHEDULE=<path> reads a local copy of the Node release schedule;
CICD_PIPELINES_OFFLINE=1 uses the dated offline list (the json block of tools.md) with no network.
"""
import datetime
import glob
import http.client
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.request
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
OFFLINE_NAME = "tools.md"
OFFLINE_HEADING = "## Offline Node support list"
SCHEDULE_URL = "https://raw.githubusercontent.com/nodejs/Release/main/schedule.json"
LOCKFILES = (("pnpm-lock.yaml", "pnpm"), ("package-lock.json", "npm"), ("yarn.lock", "yarn"))
PUBLISH_SIGNALS = ("publishConfig", "exports", "main", "module", "types", "bin", "files")
RUNNERS = ("vitest", "jest", "@playwright/test")
CONFIGS = (("vitest.config.", "vitest"), ("jest.config.", "jest"), ("playwright.config.", "@playwright/test"))
STANDARD = ("ubuntu-latest", "ubuntu-24.04", "ubuntu-22.04", "windows-latest", "windows-2025", "windows-2022",
            "macos-latest", "macos-15", "macos-14")
TOOLS = (("actionlint", "-version"), ("zizmor", "--version"), ("pinact", "--version"))
REMOTE = re.compile(r"^(?:https?://|ssh://)?(?:[^@/]+@)?github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$")


def fact(value, status, source):
    return {"value": value, "status": status, "source": source}


def read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_json(path):
    """The parsed JSON object of a file, or None when the file is missing or is not a JSON object."""
    text = read_text(path)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def run(args, timeout=30):
    """(ok, stdout, stderr) of a subprocess. A missing program, a timeout or output that is not UTF-8 is not ok."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as error:
        return False, "", f"{args[0]}: {error}"
    return done.returncode == 0, done.stdout, done.stderr


def gh_api(path):
    """(ok, parsed JSON or None, reason). Only `gh api <path>`: no method flag and no body."""
    ok, out, err = run(["gh", "api", path])
    if not ok:
        reason = next((line.strip() for line in (err + "\n" + out).splitlines() if line.strip()), "gh failed")
        return False, None, reason
    try:
        return True, json.loads(out), ""
    except ValueError:
        return False, None, "gh did not print JSON"


def github_identity(repo):
    ok, out, _ = run(["git", "-C", repo, "remote", "get-url", "origin"])
    match = REMOTE.match(out.strip()) if ok else None
    return (match.group(1), match.group(2)) if match else None


def offline_list():
    with open(os.path.join(os.path.dirname(HERE), OFFLINE_NAME), encoding="utf-8") as handle:
        text = handle.read()
    block = re.search(r"```json\n(.*?)\n```", text[text.index(OFFLINE_HEADING):], re.S)
    data = json.loads(block.group(1))
    return fact({"majors": data["majors"], "newest_lts": data["newest_lts"]}, "default",
                f"offline list {OFFLINE_NAME} dated {data['date']}")


def from_schedule(schedule, source):
    today = datetime.date.today()
    majors, lts = [], []
    for key, entry in schedule.items():
        match = re.fullmatch(r"v(\d+)", key)
        if not match or not isinstance(entry, dict):
            continue
        try:
            start = datetime.date.fromisoformat(entry["start"])
            end = datetime.date.fromisoformat(entry["end"])
            lts_date = datetime.date.fromisoformat(entry["lts"]) if "lts" in entry else None
        except (KeyError, TypeError, ValueError):
            continue
        if start <= today < end:
            majors.append(int(match.group(1)))
            if lts_date and lts_date <= today:
                lts.append(int(match.group(1)))
    if not majors:
        return None
    return fact({"majors": sorted(majors), "newest_lts": max(lts or majors)}, "detected", source)


def node_schedule():
    path = os.environ.get("CICD_PIPELINES_NODE_SCHEDULE")
    schedule, source = None, None
    if path:
        schedule, source = read_json(path), path
    elif os.environ.get("CICD_PIPELINES_OFFLINE") != "1":
        try:
            with urllib.request.urlopen(SCHEDULE_URL, timeout=10) as response:
                schedule, source = json.load(response), SCHEDULE_URL
        except (OSError, ValueError, http.client.HTTPException):
            schedule = None
    return (from_schedule(schedule, source) if isinstance(schedule, dict) else None) or offline_list()


def workspace_globs(repo, root):
    globs = []
    text = read_text(os.path.join(repo, "pnpm-workspace.yaml")) or ""
    in_packages = False
    for line in text.splitlines():
        clean = strip_comment(line)
        if flow := re.match(r"^packages:\s*(\[.*\])\s*$", clean):
            globs += inline_labels(flow.group(1))
        elif re.match(r"^packages:\s*$", clean):
            in_packages = True
        elif in_packages and (item := re.match(r"^\s*-\s*(.+?)\s*$", clean)):
            globs.append(unquote(item.group(1)))
        elif in_packages and clean.strip() and not line[0].isspace():
            in_packages = False
    workspaces = root.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    globs += [g for g in workspaces if isinstance(g, str)] if isinstance(workspaces, list) else []
    return globs


def find_packages(repo):
    """(packages, root): a sorted list of (relative path, parsed package.json or None when it is not a
    JSON object), and the root package.json object (empty when it is missing or invalid)."""
    paths = []
    if os.path.exists(os.path.join(repo, "package.json")):
        paths.append(".")
    root_data = read_json(os.path.join(repo, "package.json"))
    root = root_data or {}

    def folders(patterns):
        found = set()
        for pattern in patterns:
            for match in glob.glob(os.path.join(repo, pattern), recursive=True):
                relative = os.path.relpath(match, repo).replace(os.sep, "/")
                outside_or_dependency = relative.startswith("..") or "node_modules" in relative.split("/")
                if not outside_or_dependency and os.path.isfile(os.path.join(match, "package.json")):
                    found.add(relative)
        return found

    globs = workspace_globs(repo, root)
    included = folders([g for g in globs if not g.startswith("!")])
    excluded = folders([g[1:] for g in globs if g.startswith("!")])
    paths += sorted((included - excluded) - {"."})
    packages = [(path, root_data if path == "." else read_json(os.path.join(repo, path, "package.json")))
                for path in paths]
    return packages, root


def aggregate(entries, empty_status):
    if not entries:
        return empty_status
    statuses = {entry["status"] for entry in entries}
    return "unknown" if "unknown" in statuses else "default" if "default" in statuses else "detected"


def default_branch(repo, info, path):
    if info and isinstance(info.get("default_branch"), str):
        return fact(info["default_branch"], "detected", f"gh api {path}")
    ok, out, _ = run(["git", "-C", repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    name = out.strip().removeprefix("origin/") if ok else ""
    if name:
        return fact(name, "detected", "git symbolic-ref refs/remotes/origin/HEAD")
    return fact("main", "default", "no default branch found (no gh answer, no origin HEAD)")


def visibility(info, path):
    if info and isinstance(info.get("private"), bool):
        return fact("private" if info["private"] else "public", "detected", f"gh api {path}")
    return fact("private", "default", "repository visibility not readable (private, 2 vCPU assumed)")


def package_manager(repo, root):
    field = root.get("packageManager")
    lockfile = next((name for name, _ in LOCKFILES if os.path.exists(os.path.join(repo, name))), None)
    manager = field.split("@")[0] if isinstance(field, str) and field.split("@")[0] else None
    source = "package.json packageManager"
    if manager is None and lockfile:
        manager, source = dict(LOCKFILES)[lockfile], lockfile
    if manager is None:
        return fact({"manager": None, "lockfile": None}, "unknown", "no packageManager field and no lockfile")
    return fact({"manager": manager, "lockfile": lockfile}, "detected", source)


def node_version(repo, root, newest_lts):
    for name in (".nvmrc", ".node-version"):
        text = (read_text(os.path.join(repo, name)) or "").strip()
        if text:
            return fact(text, "detected", name)
    engines = root.get("engines")
    if isinstance(engines, dict) and isinstance(engines.get("node"), str):
        return fact(engines["node"], "detected", "package.json engines.node")
    return fact(str(newest_lts), "default", "newest LTS of supported_node_majors (no .nvmrc, .node-version or engines.node)")


def engines_fact(packages, newest_lts):
    entries = []
    for path, data in packages:
        engines = (data or {}).get("engines")
        if data is not None and isinstance(engines, dict) and isinstance(engines.get("node"), str):
            entries.append({"path": path, "value": engines["node"], "status": "detected",
                            "source": f"{path}/package.json engines.node"})
        else:
            why = "package.json is not valid JSON" if data is None else "no engines.node"
            entries.append({"path": path, "value": str(newest_lts), "status": "default",
                            "source": f"{why}: newest LTS only"})
    return fact(entries, aggregate(entries, "unknown"), "package.json of each package")


def scripts_fact(packages):
    entries = []
    for path, data in packages:
        scripts = (data or {}).get("scripts")
        names = sorted(scripts) if isinstance(scripts, dict) else []
        if data is None:
            entries.append({"path": path, "value": [], "status": "unknown",
                            "source": f"{path}/package.json is not valid JSON"})
        else:
            entries.append({"path": path, "value": names, "status": "detected",
                            "source": f"{path}/package.json scripts"})
    return fact(entries, aggregate(entries, "unknown"), "package.json of each package")


def is_published(data):
    return data.get("private") is not True and any(key in data for key in PUBLISH_SIGNALS)


def kind_fact(packages):
    entries = []
    for path, data in packages:
        if data is None:
            entries.append({"path": path, "value": "app", "status": "default",
                            "source": f"{path}/package.json is not valid JSON"})
            continue
        published = is_published(data)
        entries.append({"path": path, "value": "published" if published else "app", "status": "detected",
                        "source": f"{path}/package.json private and publish signals"})
    return fact(entries, aggregate(entries, "unknown"), "package.json of each package")


def os_claims(packages):
    claims = []
    for _, data in packages:
        values = (data or {}).get("os")
        for value in values if isinstance(values, list) else []:
            if isinstance(value, str) and value not in claims:
                claims.append(value)
    if claims:
        return fact(claims, "detected", "package.json os")
    return fact(["linux"], "default", "no os field in any package.json")


def detect_runners(repo, packages):
    found = set()
    for path, data in packages:
        for section in ("dependencies", "devDependencies"):
            deps = (data or {}).get(section)
            found |= {name for name in RUNNERS if isinstance(deps, dict) and name in deps}
        folder = os.path.join(repo, path)
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            found |= {runner for prefix, runner in CONFIGS if entry.startswith(prefix)}
    if found:
        return fact(sorted(found), "detected", "dependencies and config files")
    return fact([], "unknown", "no test runner dependency or config file (no test job)")


def monorepo(repo, root):
    has_pnpm = os.path.exists(os.path.join(repo, "pnpm-workspace.yaml"))
    if not (has_pnpm or "workspaces" in root):
        return fact({"monorepo": False, "tool": None}, "detected", "no pnpm-workspace.yaml and no workspaces field")
    tool = ("turbo" if os.path.exists(os.path.join(repo, "turbo.json"))
            else "nx" if os.path.exists(os.path.join(repo, "nx.json"))
            else "pnpm" if has_pnpm else "workspaces")
    return fact({"monorepo": True, "tool": tool}, "detected", "pnpm-workspace.yaml or workspaces field")


def strip_comment(text):
    """The text without a YAML comment (a `#` at the start of the text or after whitespace)."""
    return re.sub(r"(^|\s+)#.*$", "", text)


def unquote(text):
    return text.strip().strip("'\"")


def inline_labels(text):
    text = strip_comment(text).strip()
    if text.startswith("[") and text.endswith("]"):
        return [unquote(part) for part in text[1:-1].split(",") if part.strip()]
    return [unquote(text)] if text else []


def matrix_values(text, key):
    """Every value of a matrix key in the text: a list, a block list, or a scalar (a matrix include entry)."""
    lines = text.splitlines()
    values = []
    for number, line in enumerate(lines):
        match = re.match(rf"^\s*(?:-\s+)?{re.escape(key)}:\s*(.*?)\s*$", line)
        if not match:
            continue
        rest = strip_comment(match.group(1))
        if rest.startswith("["):
            values += inline_labels(rest)
        elif rest:
            values.append(unquote(rest))
        else:
            for following in lines[number + 1:]:
                stripped = following.strip()
                if stripped.startswith("- "):
                    values.append(unquote(strip_comment(stripped[2:])))
                elif stripped and not stripped.startswith("#"):
                    break
    return values


def runs_on(text):
    lines = text.splitlines()
    labels = []
    for number, line in enumerate(lines):
        match = re.match(r"^(\s*)runs-on:\s*(.*?)\s*$", line)
        if not match:
            continue
        indent, rest = len(match.group(1)), strip_comment(match.group(2))
        if rest:
            labels += inline_labels(rest)
            continue
        for following in lines[number + 1:]:
            stripped = following.strip()
            if not stripped or stripped.startswith("#"):
                continue
            child = len(following) - len(following.lstrip())
            if child < indent or (child == indent and not stripped.startswith("- ")):
                break
            if stripped.startswith("- "):
                labels.append(unquote(strip_comment(stripped[2:])))
            elif stripped.startswith("labels:"):
                labels += inline_labels(stripped[len("labels:"):])
            elif stripped.startswith("group:"):
                labels.append(unquote(stripped[len("group:"):]))
    resolved = []
    for label in labels:
        expression = re.fullmatch(r"\$\{\{\s*matrix\.(\w+)\s*\}\}", label)
        resolved += (matrix_values(text, expression.group(1)) if expression else []) or [label]
    return resolved


def runner_labels(repo, workflows, visibility_value):
    entries, seen = [], set()
    for workflow in workflows:
        for label in runs_on(read_text(os.path.join(repo, workflow)) or ""):
            if label in seen:
                continue
            seen.add(label)
            standard = label in STANDARD
            vcpus = (3 if label.startswith("macos-") else 4 if visibility_value == "public" else 2) if standard else None
            entries.append({"label": label, "kind": "standard" if standard else "custom", "vcpus": vcpus,
                            "status": "detected" if standard else "unknown", "source": workflow})
    return fact(entries, aggregate(entries, "detected"), ".github/workflows runs-on values")


# A gh answer of another shape than the GitHub API documents raises one of these; the facts then are unknown.
SHAPE_ERRORS = (KeyError, TypeError, AttributeError, ValueError)


def names_from_protection(data):
    return [*data["contexts"], *(check["context"] for check in data["checks"])]


def names_from_rulesets(data):
    names = []
    for item in data:
        if item["type"] == "required_status_checks":
            names += [check["context"] for check in item["parameters"]["required_status_checks"]]
    return names


def required_checks(identity, branch):
    if not identity:
        return fact(None, "unknown", "no GitHub remote")
    base = f"repos/{identity[0]}/{identity[1]}"
    protection = f"{base}/branches/{quote(branch, safe='')}/protection/required_status_checks"
    rules = f"{base}/rules/branches/{quote(branch, safe='')}"
    ok, protection_data, reason = gh_api(protection)
    if not ok and "Branch not protected" not in reason:
        return fact(None, "unknown", f"gh api {protection}: {reason}")
    ok_rules, rules_data, rules_reason = gh_api(rules)
    if not ok_rules:
        return fact(None, "unknown", f"gh api {rules}: {rules_reason}")
    try:
        names = (names_from_protection(protection_data) if ok else []) + names_from_rulesets(rules_data)
        if not all(isinstance(name, str) for name in names):
            raise TypeError("a check name is not a string")
        names = sorted(set(names))
    except SHAPE_ERRORS:
        return fact(None, "unknown", f"gh api {protection} or {rules}: unexpected answer shape")
    return fact(names, "detected", f"gh api {protection} and gh api {rules}")


def to_seconds(stamp):
    return datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()


def workflow_history(identity, workflow, branch=None):
    """The last 10 successful runs of a workflow file (of one branch when `branch` is given), with the median of each job."""
    if not identity:
        return fact(None, "unknown", "no GitHub remote")
    base = f"repos/{identity[0]}/{identity[1]}"
    branch_query = f"branch={quote(branch, safe='')}&" if branch else ""
    path = f"{base}/actions/workflows/{workflow}/runs?{branch_query}status=success&per_page=10"
    ok, data, reason = gh_api(path)
    if not ok:
        return fact(None, "unknown", f"gh api {path}: {reason}")
    try:
        runs = data["workflow_runs"]
        if len(runs) < 10:
            return fact(None, "unknown",
                        f"fewer than 10 successful runs of {workflow}" + (" on the default branch" if branch else ""))
        durations = {}
        for workflow_run in runs:
            jobs_path = f"{base}/actions/runs/{workflow_run['id']}/jobs?per_page=100"
            ok, jobs_data, reason = gh_api(jobs_path)
            if not ok:
                return fact(None, "unknown", f"gh api {jobs_path}: {reason}")
            for item in jobs_data["jobs"]:
                if item.get("conclusion") == "success" and item.get("started_at") and item.get("completed_at"):
                    durations.setdefault(item["name"], []).append(
                        to_seconds(item["completed_at"]) - to_seconds(item["started_at"]))
        jobs = {name: {"median_seconds": round(statistics.median(values))} for name, values in durations.items()}
    except SHAPE_ERRORS:
        return fact(None, "unknown", f"gh api {path} or the jobs of a run: unexpected answer shape")
    return fact({"runs": len(runs), "jobs": jobs}, "detected", f"gh api {path} and the jobs of each run")


def repo_base(identity):
    return f"repos/{identity[0]}/{identity[1]}"


def environment_entry(item):
    rules = item.get("protection_rules") or []
    policy = item.get("deployment_branch_policy")
    timers = [rule["wait_timer"] for rule in rules if rule.get("type") == "wait_timer"]
    entry = {"name": item["name"],
             "reviewers": any(rule.get("type") == "required_reviewers" for rule in rules),
             "wait_timer": timers[0] if timers else 0,
             "branch_policy": ("none" if policy is None
                               else "protected_branches" if policy.get("protected_branches") is True else "custom"),
             "admin_bypass": item["can_admins_bypass"]}
    if not (isinstance(entry["name"], str) and isinstance(entry["wait_timer"], int)
            and isinstance(entry["admin_bypass"], bool)):
        raise TypeError("an environment field has the wrong type")
    return entry


def environments(identity):
    if not identity:
        return fact([], "default", "no GitHub remote (treated as none)")
    path = f"{repo_base(identity)}/environments"
    ok, data, reason = gh_api(path)
    if not ok:
        return fact([], "default", f"gh api {path}: {reason} (treated as none)")
    try:
        entries = [environment_entry(item) for item in data["environments"]]
    except SHAPE_ERRORS:
        return fact([], "default", f"gh api {path}: unexpected answer shape (treated as none)")
    return fact(entries, "detected", f"gh api {path}")


PLAN_NOTE = "reviewers are proposed; a private repo may need GitHub Enterprise"


def plan(identity, info, seen):
    if seen["status"] == "default":
        return fact({"visibility": "private", "plan": None, "reviewers_available": True}, "default",
                    f"visibility not readable (private assumed): {PLAN_NOTE}")
    if seen["value"] == "public":
        return fact({"visibility": "public", "plan": None, "reviewers_available": True}, "detected",
                    "public repo: reviewers are available on every plan")
    owner = info.get("owner")
    if not (isinstance(owner, dict) and owner.get("type") == "Organization"):
        return fact({"visibility": "private", "plan": None, "reviewers_available": True}, "default",
                    f"private repo of a user (plan not readable): {PLAN_NOTE}")
    path = f"orgs/{identity[0]}"
    ok, data, reason = gh_api(path)
    try:
        name = data["plan"]["name"] if ok else None
    except SHAPE_ERRORS:
        name = None
    if not isinstance(name, str) or not name:
        why = reason if not ok else "no plan.name in the answer (the token is not an org owner)"
        return fact({"visibility": "private", "plan": None, "reviewers_available": True}, "default",
                    f"gh api {path}: {why}: {PLAN_NOTE}")
    return fact({"visibility": "private", "plan": name, "reviewers_available": name.lower() != "free"},
                "detected", f"gh api {path}")


def rulesets(identity):
    if not identity:
        return fact(None, "unknown", "no GitHub remote")
    path = f"{repo_base(identity)}/rulesets"
    ok, data, reason = gh_api(path)
    if not ok:
        return fact(None, "unknown", f"gh api {path}: {reason}")
    try:
        if not isinstance(data, list):
            raise TypeError("the answer is not a list")
        value = [{"name": item["name"], "target": item["target"], "enforcement": item["enforcement"]}
                 for item in data]
    except SHAPE_ERRORS:
        return fact(None, "unknown", f"gh api {path}: unexpected answer shape")
    return fact(value, "detected", f"gh api {path}")


def classic_protection(identity, branch):
    if not identity:
        return fact(None, "unknown", "no GitHub remote")
    path = f"{repo_base(identity)}/branches/{quote(branch, safe='')}/protection"
    ok, data, reason = gh_api(path)
    if not ok:
        if "Branch not protected" in reason:
            return fact({"branch": branch, "protected": False, "required_pull_request_reviews": False,
                         "enforce_admins": False}, "detected", f"gh api {path}: {reason}")
        return fact(None, "unknown", f"gh api {path}: {reason}")
    try:
        value = {"branch": branch, "protected": True,
                 "required_pull_request_reviews": "required_pull_request_reviews" in data,
                 "enforce_admins": data["enforce_admins"]["enabled"]}
        if not isinstance(data, dict) or not isinstance(value["enforce_admins"], bool):
            raise TypeError("the answer has the wrong shape")
    except SHAPE_ERRORS:
        return fact(None, "unknown", f"gh api {path}: unexpected answer shape")
    return fact(value, "detected", f"gh api {path}")


# Each table maps a kind to its patterns. A pattern matches on one workflow line (comment removed), with each
# space matching one or more spaces, and it must end at a character that is not a letter, a digit, `_` or `-`.
DEPLOY_TARGETS = (
    ("aws", ("uses: aws-actions/configure-aws-credentials",)),
    ("s3", ("aws s3 sync", "aws s3 cp")),
    ("lambda", ("aws lambda update-function-code", "uses: aws-actions/aws-lambda-deploy")),
    ("ecs", ("aws ecs", "uses: aws-actions/amazon-ecs-deploy-task-definition")),
    ("cloudfront", ("aws cloudfront create-invalidation",)),
    ("github-pages", ("uses: actions/deploy-pages",)),
    ("cloudflare", ("uses: cloudflare/wrangler-action", "wrangler deploy", "wrangler pages deploy")),
    ("vercel", ("vercel deploy", "vercel --prod", "uses: amondnet/vercel-action")),
    ("netlify", ("netlify deploy", "uses: nwtgck/actions-netlify")),
    ("container-registry", ("uses: docker/build-push-action", "docker push")),
)
IAC_TOOLS = (
    ("terraform", ("uses: hashicorp/setup-terraform", "terraform init", "terraform plan", "terraform apply")),
    ("opentofu", ("uses: opentofu/setup-opentofu", "tofu init", "tofu plan", "tofu apply")),
    ("cdk", ("cdk deploy", "cdk synth", "cdk diff")),
    ("pulumi", ("uses: pulumi/actions", "pulumi up", "pulumi preview")),
    ("serverless", ("serverless deploy", "sls deploy")),
    ("sam", ("sam deploy", "uses: aws-actions/setup-sam")),
    ("cloudformation", ("aws cloudformation deploy", "aws cloudformation create-stack",
                        "aws cloudformation update-stack")),
)
END = r"(?![\w-])"


def pattern_regex(pattern):
    if pattern.startswith("uses: "):
        return re.compile(r"uses:\s+['\"]?" + re.escape(pattern[len("uses: "):]) + END)
    return re.compile(r"\s+".join(re.escape(word) for word in pattern.split(" ")) + END)


def workflow_lines(repo, workflows):
    return [strip_comment(line) for workflow in workflows
            for line in (read_text(os.path.join(repo, workflow)) or "").splitlines()]


def tools_found(table, lines):
    return sorted(kind for kind, patterns in table
                  if any(pattern_regex(pattern).search(line) for pattern in patterns for line in lines))


def deploy_targets(lines):
    found = tools_found(DEPLOY_TARGETS, lines)
    if found:
        return fact(found, "detected", ".github/workflows steps")
    return fact([], "default", "no workflow step shows a deploy target (none)")


def iac_tools(lines):
    found = tools_found(IAC_TOOLS, lines)
    if found:
        return fact(found, "detected", ".github/workflows steps")
    return fact([], "default", "no workflow step shows an IaC tool (none)")


def aws_variables(lines):
    """The names of the vars.* on the role-to-assume and aws-region lines. Never a value."""
    names = {"role": set(), "region": set()}
    for line in lines:
        match = re.match(r"^\s*(?:-\s+)?(role-to-assume|aws-region):(.*)$", line)
        if not match:
            continue
        key = "role" if match.group(1) == "role-to-assume" else "region"
        for expression in re.findall(r"\$\{\{(.*?)\}\}", match.group(2)):
            names[key] |= {f"vars.{name}" for name in re.findall(r"\bvars\.(\w+)", expression)}
    placeholders = {"role": ["vars.AWS_ROLE_<ENV>"], "region": ["vars.AWS_REGION"]}
    value = {key: sorted(names[key]) or placeholders[key] for key in names}
    missing = [key for key in names if not names[key]]
    if not missing:
        return fact(value, "detected", ".github/workflows role-to-assume and aws-region lines (names only)")
    used = ", ".join(f"{key} {placeholders[key][0]}" for key in missing)
    return fact(value, "default", f"no vars.* name found for: {used}; these are placeholders, replace them with the "
                                  "repo's own variable names")


def release_tool(repo, root):
    dependencies = set()
    for section in ("dependencies", "devDependencies"):
        deps = root.get(section)
        dependencies |= set(deps) if isinstance(deps, dict) else set()
    try:
        entries = os.listdir(repo)
    except OSError:
        entries = []
    found = set()
    if os.path.isdir(os.path.join(repo, ".changeset")) or "@changesets/cli" in dependencies:
        found.add("changesets")
    if ({"release-please-config.json", ".release-please-manifest.json"} & set(entries)
            or "release-please" in dependencies):
        found.add("release-please")
    if (any(entry.startswith((".releaserc", "release.config.")) for entry in entries)
            or "semantic-release" in dependencies):
        found.add("semantic-release")
    if any(entry.startswith(".release-it.") for entry in entries) or "release-it" in dependencies:
        found.add("release-it")
    if found:
        return fact(sorted(found), "detected", "files at the repo root and package.json dependencies")
    return fact([], "default", "no release tool file or dependency (none, so create adds Changesets)")


def publish_target(packages):
    targets = set()
    for _, data in packages:
        if data is None or not is_published(data):
            continue
        config = data.get("publishConfig")
        registry = config.get("registry") if isinstance(config, dict) else None
        if not isinstance(registry, str) or registry.rstrip("/") in ("", "https://registry.npmjs.org"):
            registry = "npmjs"
        targets.add(registry)
    if targets:
        return fact(sorted(targets), "detected", "package.json publishConfig.registry of the published packages")
    return fact(["npmjs"], "default", "no published package (npmjs)")


TAG_SHAPES = (
    ("v*", re.compile(r"^v\d+\.\d+\.\d+(?:[-+].*)?$")),
    ("[0-9]*", re.compile(r"^\d+\.\d+\.\d+(?:[-+].*)?$")),
    ("*@*", re.compile(r"^.+@\d+\.\d+\.\d+(?:[-+].*)?$")),
)


def release_tag_pattern(repo):
    ok, out, _ = run(["git", "-C", repo, "tag", "--list"])
    if not ok:
        return fact("v*", "default", "git tag --list failed (v*)")
    tags = out.split()
    counts = {glob_: sum(1 for tag in tags if shape.match(tag)) for glob_, shape in TAG_SHAPES}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        return fact("v*", "default", "no tag has a version shape (v*)")
    return fact(best, "detected", "git tag --list")


def is_public_package(data):
    config = data.get("publishConfig")
    access = config.get("access") if isinstance(config, dict) else None
    scoped = isinstance(data.get("name"), str) and data["name"].startswith("@")
    return is_published(data) and access != "restricted" and (not scoped or access == "public")


def provenance(seen, packages):
    if seen["status"] == "default":
        return fact(False, "default", "visibility not readable (provenance not automatic)")
    public = any(is_public_package(data) for _, data in packages if data is not None)
    return fact(seen["value"] == "public" and public, "detected",
                "visibility and the publish fields of package.json (automatic only for a public package of a public repo)")


def installed_tools():
    tools = {}
    for name, flag in TOOLS:
        path = shutil.which(name)
        version = None
        if path:
            ok, out, _ = run([path, flag], timeout=10)
            version = (out.strip().splitlines() or [None])[0] if ok else None
        tools[name] = {"installed": path is not None, "version": version}
    return fact(tools, "detected", "PATH: " + ", ".join(name for name, _ in TOOLS))


def collect(repo):
    identity = github_identity(repo)
    info_path = f"repos/{identity[0]}/{identity[1]}" if identity else None
    info = gh_api(info_path)[1] if identity else None
    info = info if isinstance(info, dict) else None
    packages, root = find_packages(repo)
    node = node_schedule()
    newest_lts = node["value"]["newest_lts"]
    branch = default_branch(repo, info, info_path)
    seen = visibility(info, info_path)
    workflows = sorted(os.path.relpath(path, repo).replace(os.sep, "/")
                       for pattern in ("*.yml", "*.yaml")
                       for path in glob.glob(os.path.join(repo, ".github", "workflows", pattern)))
    lines = workflow_lines(repo, workflows)
    return {
        "default_branch": branch,
        "package_manager": package_manager(repo, root),
        "node_version_app": node_version(repo, root, newest_lts),
        "engines": engines_fact(packages, newest_lts),
        "scripts": scripts_fact(packages),
        "package_kind": kind_fact(packages),
        "os_claims": os_claims(packages),
        "test_runners": detect_runners(repo, packages),
        "monorepo": monorepo(repo, root),
        "visibility": seen,
        "runner_labels": runner_labels(repo, workflows, seen["value"]),
        "required_checks": required_checks(identity, branch["value"]),
        "run_history": workflow_history(identity, "ci.yml", branch["value"]),
        "existing_workflows": fact(workflows, "detected", ".github/workflows"),
        "installed_tools": installed_tools(),
        "supported_node_majors": node,
        "environments": environments(identity),
        "plan": plan(identity, info, seen),
        "rulesets": rulesets(identity),
        "classic_protection": classic_protection(identity, branch["value"]),
        "deploy_targets": deploy_targets(lines),
        "iac_tools": iac_tools(lines),
        "aws_variables": aws_variables(lines),
        "release_tool": release_tool(repo, root),
        "publish_target": publish_target(packages),
        "release_tag_pattern": release_tag_pattern(repo),
        "provenance": provenance(seen, packages),
        "deploy_history": workflow_history(identity, "deploy.yml"),
    }


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        print("usage: intake.py REPO_PATH (a folder)", file=sys.stderr)
        return 2
    print(json.dumps(collect(os.path.abspath(argv[1])), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
