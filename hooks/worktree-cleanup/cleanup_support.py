import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CLEANUP = os.path.join(HERE, "cleanup")
HANDLE = "term_test"

# One stub for `orca` and `gh`. It logs "<name> <args>" to calls.log and answers from config.json,
# keyed by "<name> <first two args>". Calls of `orca worktree rm` can remove the worktree like Orca does.
STUB = """#!/usr/bin/env python3
import json, os, subprocess, sys
d = os.environ["STUB_DIR"]
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.path.join(d, "calls.log"), "a") as f:
    f.write(name + " " + " ".join(args) + "\\n")
cfg = json.load(open(os.path.join(d, "config.json")))
key = " ".join([name] + args[:2])
entry = cfg.get(key, {"rc": 1, "stderr": "unstubbed call"})
effect = cfg.get("rm_effect")
if key == "orca worktree rm" and effect and entry.get("rc", 0) == 0:
    command = "sleep %s; git -C %s worktree remove --force %s" % (effect.get("delay", 0), effect["repo"], effect["path"])
    if effect.get("delete_branch"):
        command += "; git -C %s branch -D %s" % (effect["repo"], effect["branch"])
    if effect.get("delay"):
        subprocess.Popen(["sh", "-c", command], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["sh", "-c", command], check=True)
sys.stdout.write(entry.get("stdout", ""))
sys.stderr.write(entry.get("stderr", ""))
sys.exit(entry.get("rc", 0))
"""


def git(*args, cwd=None, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


class CleanupCase(unittest.TestCase):
    """A bare remote, a main checkout on main, and a linked worktree on BRANCH whose tip is pushed."""

    BRANCH = "feat"

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.env = dict(os.environ, HOME=self.root, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null",
                        GIT_CONFIG_SYSTEM="/dev/null")
        self.remote = os.path.join(self.root, "remote.git")
        self.main = os.path.join(self.root, "main")
        self.wt = os.path.join(self.root, "wt")
        git("init", "-q", "--bare", "-b", "main", self.remote, env=self.env)
        git("clone", "-q", self.remote, self.main, env=self.env)
        git("checkout", "-q", "-b", "main", cwd=self.main, env=self.env)
        self.commit(self.main, "base.txt")
        git("push", "-q", "-u", "origin", "main", cwd=self.main, env=self.env)
        git("worktree", "add", "-q", "-b", self.BRANCH, self.wt, cwd=self.main, env=self.env)
        self.commit(self.wt, "work.txt")
        git("push", "-q", "origin", self.BRANCH, cwd=self.wt, env=self.env)
        self.tip = self.git_out(self.wt, "rev-parse", "HEAD")
        self.stub_dir = os.path.join(self.root, "stubs")
        os.mkdir(self.stub_dir)
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.bin)
        for name in ("orca", "gh", "docker"):
            path = os.path.join(self.bin, name)
            with open(path, "w") as f:
                f.write(STUB)
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self.config = {}
        self.anchor_id = "anchor-id"
        self.wt_id = "wt-id"
        self.stub_show(parent=self.anchor_id)
        self.stub_terminal(self.anchor_id)
        self.stub_gh_merged()
        self.stub("gh repo view", json.dumps({"defaultBranchRef": {"name": "main"}}))
        self.stub("docker compose ls", "[]")
        self.stub_rm_effect()

    def commit(self, repo, name):
        with open(os.path.join(repo, name), "w") as f:
            f.write(name)
        git("add", name, cwd=repo, env=self.env)
        git("commit", "-q", "-m", name, cwd=repo, env=self.env)

    def git_out(self, repo, *args):
        return git(*args, cwd=repo, env=self.env).stdout.strip()

    def remote_has(self, branch):
        return bool(self.git_out(self.main, "ls-remote", "origin", f"refs/heads/{branch}"))

    def local_has(self, branch):
        return bool(self.git_out(self.main, "branch", "--list", branch))

    def stub(self, key, stdout="", rc=0, stderr=""):
        self.config[key] = {"stdout": stdout, "rc": rc, "stderr": stderr}
        with open(os.path.join(self.stub_dir, "config.json"), "w") as f:
            json.dump(self.config, f)

    def stub_show(self, parent=None, caller=None, ok=True, rc=0):
        worktree = {"id": self.wt_id, "parentWorktreeId": parent}
        if caller is not None:
            worktree["cliProvenance"] = {"callerTerminalHandle": caller}
        self.stub("orca worktree show", json.dumps({"ok": ok, "result": {"worktree": worktree}}), rc=rc)

    def stub_terminal(self, worktree_id, rc=0):
        self.stub("orca terminal show", json.dumps({"ok": True, "result": {"terminal": {"worktreeId": worktree_id}}}), rc=rc)

    def stub_gh_merged(self, prs=None, rc=0):
        if prs is None:
            prs = [{"number": 7, "headRefOid": self.tip, "baseRefName": "main"}]
        self.stub("gh pr list", json.dumps(prs), rc=rc)

    def stub_rm_effect(self, delay=0, delete_branch=False):
        self.config["rm_effect"] = {"repo": self.main, "path": self.wt, "branch": self.BRANCH,
                                    "delay": delay, "delete_branch": delete_branch}
        self.stub("orca worktree rm", json.dumps({"ok": True}))

    def no_docker_path(self):
        """A PATH folder with the orca and gh stubs and the real tools the script and the stubs need, but no docker."""
        folder = os.path.join(self.root, "bin-no-docker")
        os.makedirs(folder, exist_ok=True)
        for name in ("orca", "gh"):
            link = os.path.join(folder, name)
            if not os.path.lexists(link):
                os.symlink(os.path.join(self.bin, name), link)
        for name in ("git", "python3", "sh", "sleep"):
            link = os.path.join(folder, name)
            if not os.path.lexists(link):
                os.symlink(shutil.which(name), link)
        return folder

    def run_cleanup(self, *args, handle=HANDLE, wait_interval="0.05", wait_limit="1", cwd=None, no_docker=False):
        path = self.no_docker_path() if no_docker else self.bin + os.pathsep + os.environ["PATH"]
        env = dict(self.env, PATH=path, STUB_DIR=self.stub_dir,
                   WORKTREE_CLEANUP_WAIT_INTERVAL=wait_interval, WORKTREE_CLEANUP_WAIT_LIMIT=wait_limit)
        if handle is None:
            env.pop("ORCA_TERMINAL_HANDLE", None)
        else:
            env["ORCA_TERMINAL_HANDLE"] = handle
        return subprocess.run([CLEANUP, *args], capture_output=True, text=True, env=env, cwd=cwd)

    def calls(self):
        path = os.path.join(self.stub_dir, "calls.log")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return f.read().splitlines()

    def rm_calls(self):
        return [c for c in self.calls() if c.startswith("orca worktree rm")]

    def lines(self, result):
        return result.stdout.splitlines()

    def starts(self, result, marker):
        return [line for line in self.lines(result) if line.startswith(marker)]

    def assert_unchanged(self):
        self.assertTrue(self.remote_has(self.BRANCH))
        self.assertTrue(os.path.isdir(self.wt))
        self.assertTrue(self.local_has(self.BRANCH))
        self.assertEqual(self.git_out(self.main, "branch", "--show-current"), "main")
        self.assertEqual(self.rm_calls(), [])
