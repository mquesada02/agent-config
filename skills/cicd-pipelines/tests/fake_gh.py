"""A fake `gh` (and fake tools) on PATH for the intake tests (a helper module, not a test file).

The fake `gh` answers `gh api <path>` from a JSON scenario file and logs every call. The PATH of a
run holds only the sandbox `bin` folder, which holds the fake `gh`, optional fake tools and a link to
the real `git`, so a real `gh`, `actionlint` or `zizmor` on the machine never reaches a test.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

from skill_files import SKILL

INTAKE = os.path.join(SKILL, "scripts", "intake.py")

GH_SCRIPT = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as handle:
    handle.write(json.dumps(args) + "\\n")
with open(os.environ["FAKE_GH_SCENARIO"]) as handle:
    routes = json.load(handle)
route = routes.get(args[1]) if len(args) == 2 and args[0] == "api" else None
if route is None:
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
sys.stdout.write(route["stdout"])
sys.stderr.write(route["stderr"])
sys.exit(route["exit"])
"""

TOOL_SCRIPT = """#!{python}
import sys
if {fail}:
    sys.exit(3)
print({version!r})
"""


RAW_SCRIPT = """#!{python}
import sys
sys.stdout.buffer.write({data!r})
"""


class Sandbox:
    """A temporary folder with a fake `gh`, fake tools and fixture repos."""

    def __init__(self, gh=True):
        self._tmp = tempfile.TemporaryDirectory(prefix="intake-test-")
        self.root = self._tmp.name
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.bin)
        self.home = os.path.join(self.root, "home")
        os.mkdir(self.home)
        self.scenario = os.path.join(self.root, "scenario.json")
        self.log = os.path.join(self.root, "gh.log")
        self._routes = {}
        self._write_scenario()
        open(self.log, "w").close()
        os.symlink(shutil.which("git"), os.path.join(self.bin, "git"))
        if gh:
            self._executable("gh", GH_SCRIPT.format(python=sys.executable))
        self._count = 0

    def cleanup(self):
        self._tmp.cleanup()

    def _executable(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o755)

    def _write_scenario(self):
        with open(self.scenario, "w", encoding="utf-8") as handle:
            json.dump(self._routes, handle)

    def route(self, path, body=None, exit=0, stderr=""):
        """Answer `gh api <path>` with `body` (JSON-encoded unless it is a string) and exit code `exit`."""
        stdout = body if isinstance(body, str) else json.dumps(body)
        self._routes[path] = {"stdout": stdout, "stderr": stderr, "exit": exit}
        self._write_scenario()

    def tool(self, name, version="1.0.0", fail=False):
        """Put a fake tool on PATH. It prints `version` as its only line, or exits 3 when `fail`."""
        self._executable(name, TOOL_SCRIPT.format(python=sys.executable, version=version, fail=fail))

    def raw_output(self, name, data):
        """Replace the program `name` on PATH by a fake that prints the bytes `data` and exits 0."""
        self._executable(name, RAW_SCRIPT.format(python=sys.executable, data=data))

    def repo(self, files, remote="https://github.com/acme/widget.git"):
        """Create a git repo with `files` (a map of path to text) and an `origin` remote (None for no remote)."""
        self._count += 1
        path = os.path.join(self.root, f"repo{self._count}")
        os.mkdir(path)
        self.git(path, "init", "-q")
        if remote:
            self.git(path, "remote", "add", "origin", remote)
        for name, text in files.items():
            full = os.path.join(path, name)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as handle:
                handle.write(text if isinstance(text, str) else json.dumps(text))
        return path

    def git(self, path, *args):
        subprocess.run(["git", "-C", path, *args], check=True, env=self.env(), capture_output=True)

    def env(self, offline=True, schedule=None):
        env = {"PATH": self.bin, "HOME": self.home, "FAKE_GH_SCENARIO": self.scenario, "FAKE_GH_LOG": self.log}
        if offline:
            env["CI_PIPELINES_OFFLINE"] = "1"
        if schedule:
            env["CI_PIPELINES_NODE_SCHEDULE"] = schedule
        return env

    def run(self, *args, offline=True, schedule=None):
        """Run the intake script with `args`. Returns the finished process (text output)."""
        return subprocess.run([sys.executable, INTAKE, *args], env=self.env(offline, schedule),
                              capture_output=True, text=True)

    def facts(self, repo, **kwargs):
        """Run the script on `repo`, check that it exits 0, and return the JSON object."""
        done = self.run(repo, **kwargs)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    def calls(self):
        """The argument lists of every `gh` call so far."""
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
