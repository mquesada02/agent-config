import json
import os
import subprocess
import unittest

from cleanup_support import HERE, HANDLE, CleanupCase

LIST_OWNED = os.path.join(HERE, "list-owned")
REPO_ID = "repo-test"
SKIP = "! ~/.claude/hooks/worktree-cleanup/cleanup --skip-ownership "


class ListCase(CleanupCase):
    """The worktree `wt` is the only non-main row of the repo. Its creator is `term_a`, which is gone, and no other proof holds."""

    def setUp(self):
        super().setUp()
        self.tmp = os.path.join(self.root, "tmp")
        self.folder = os.path.join(self.tmp, "claude-context-handoff")
        os.makedirs(self.folder, mode=0o700)
        self.env["TMPDIR"] = self.tmp
        self.stub("orca worktree show", json.dumps({"ok": True, "result": {"worktree": {"id": "current", "repoId": REPO_ID}}}))
        self.stub_gone("term_a")
        self.stub_gh_prs([])
        self.stub("orca terminal list", json.dumps({"ok": True, "result": {"terminals": [{"handle": "t1"}, {"handle": "t2"}]}}))
        self.rows = [self.row()]
        self.stub_rows()

    def row(self, **fields):
        row = {"id": self.wt_id, "repoId": REPO_ID, "path": self.wt, "branch": f"refs/heads/{self.BRANCH}", "isMainWorktree": False,
               "isArchived": False, "parentWorktreeId": "other", "cliProvenance": {"callerTerminalHandle": "term_a"}}
        row.update(fields)
        return row

    def stub_rows(self):
        self.stub("orca worktree list", json.dumps({"ok": True, "result": {"worktrees": self.rows, "truncated": False}}))

    def stub_gone(self, handle):
        self.stub(f"orca terminal show --terminal {handle} --json", rc=1, stderr="no such terminal")

    def stub_gh_prs(self, prs):
        self.stub("gh pr list", json.dumps(prs))

    def write_lineage(self, *links):
        text = "".join(json.dumps({"successor": s, "predecessor": p, "time": 1.0, "predecessor_session": "x", "successor_session": "y"}) + "\n"
                       for s, p in links)
        with open(os.path.join(self.folder, "lineage.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(text)

    def list_owned(self, handle=HANDLE):
        env = dict(self.env, PATH=self.bin + os.pathsep + os.environ["PATH"], STUB_DIR=self.stub_dir)
        env["ORCA_TERMINAL_HANDLE"] = handle
        return subprocess.run([LIST_OWNED], capture_output=True, text=True, env=env, cwd=self.wt)

    def section(self, result, start, end):
        text = result.stdout
        return text[text.index(start):text.index(end)]

    def assert_owned(self, result, reason):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"owned: {reason};", self.section(result, "Owned worktrees", "Orphans"))
        self.assertNotIn(SKIP, result.stdout)

    def assert_orphan(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Owned worktrees (0):", result.stdout)
        self.assertIn(SKIP + self.wt, self.lines(result))


class OwnedTest(ListCase):
    def test_own_handle(self):
        self.rows = [self.row(cliProvenance={"callerTerminalHandle": HANDLE})]
        self.stub_rows()
        self.assert_owned(self.list_owned(), "own handle")

    def test_predecessor_chain(self):
        self.write_lineage((HANDLE, "term_a"))
        self.assert_owned(self.list_owned(), "predecessor chain")

    def test_chain_with_a_missing_line_is_an_orphan(self):
        self.write_lineage((HANDLE, "term_b"))
        self.assert_orphan(self.list_owned())

    def test_parent_anchor(self):
        self.rows = [self.row(parentWorktreeId=self.anchor_id)]
        self.stub_rows()
        self.assert_owned(self.list_owned(), "parent anchor")

    def test_worker_creator(self):
        self.stub_run_current()
        self.stub_worker_pages(self.worker_page([self.worker_row(worktree=self.wt_id, handle="term_worker")]))
        self.assert_owned(self.list_owned(), "Run worker")

    def test_other_repo_is_not_listed(self):
        self.rows = [self.row(repoId="other-repo", cliProvenance={"callerTerminalHandle": HANDLE})]
        self.stub_rows()
        result = self.list_owned()
        self.assertNotIn(self.wt, result.stdout)
        self.assertIn("Owned worktrees (0):", result.stdout)
        self.assertIn("Orphans (0):", result.stdout)

    def test_main_checkout_is_not_listed(self):
        self.rows = [self.row(isMainWorktree=True, cliProvenance={"callerTerminalHandle": HANDLE})]
        self.stub_rows()
        self.assertNotIn(self.wt, self.list_owned().stdout)


class StateTest(ListCase):
    def owned_state(self, result):
        return self.section(result, "Owned worktrees", "Orphans")

    def setUp(self):
        super().setUp()
        self.rows = [self.row(cliProvenance={"callerTerminalHandle": HANDLE})]
        self.stub_rows()

    def test_a_pushed_clean_worktree_with_a_merged_pr(self):
        self.stub_gh_prs([{"number": 7, "state": "MERGED", "headRefOid": self.tip}])
        state = self.owned_state(self.list_owned())
        for text in ("clean", "pushed", "PR #7 MERGED", "2 live terminals", "no compose stack"):
            self.assertIn(text, state)

    def test_a_pushed_branch_without_a_pr(self):
        state = self.owned_state(self.list_owned())
        self.assertIn("; pushed; no PR;", state)

    def test_a_new_empty_worktree_is_owned_and_not_merged(self):
        fresh = os.path.join(self.root, "fresh")
        self.git_out(self.main, "worktree", "add", "-q", "-b", "fresh", fresh, "main")
        self.rows = [self.row(id="fresh-id", path=fresh, branch="refs/heads/fresh", cliProvenance={"callerTerminalHandle": HANDLE})]
        self.stub_rows()
        state = self.owned_state(self.list_owned())
        self.assertIn(f"{fresh} [refs/heads/fresh]", state)
        self.assertIn("; clean; not pushed; no PR;", state)
        self.assertNotIn("MERGED", state)

    def test_a_dirty_worktree_and_a_compose_stack(self):
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("x")
        self.stub("docker compose ls", json.dumps([{"Name": "stack", "ConfigFiles": os.path.join(self.wt, "compose.yml")}]))
        state = self.owned_state(self.list_owned())
        self.assertIn("uncommitted or untracked changes", state)
        self.assertIn("stack stack has a config file in the worktree", state)


class OrphanTest(ListCase):
    def test_an_orphan_gets_the_skip_command(self):
        result = self.list_owned()
        self.assert_orphan(result)
        self.assertIn(f"{self.wt} [refs/heads/{self.BRANCH}]", self.section(result, "Orphans", "Not listed"))

    def test_a_worktree_without_a_creator_is_an_orphan(self):
        self.rows = [self.row(cliProvenance=None)]
        self.stub_rows()
        self.assert_orphan(self.list_owned())

    def test_a_worktree_of_a_live_creator_is_not_claimed(self):
        self.stub_terminal(self.anchor_id)
        self.stub("orca terminal show --terminal term_a --json", json.dumps({"ok": True, "result": {"terminal": {"worktreeId": "other"}}}))
        result = self.list_owned()
        self.assertIn("Owned worktrees (0):", result.stdout)
        self.assertIn("Orphans (0):", result.stdout)
        self.assertIn("Not listed: 1 worktrees", result.stdout)

    def test_the_script_removes_nothing(self):
        self.list_owned()
        self.assert_unchanged()
        self.assertEqual([c for c in self.calls() if c.startswith(("gh pr create", "orca terminal close"))], [])


class NoOrcaTest(ListCase):
    def test_orca_cannot_be_read(self):
        self.stub("orca worktree show", rc=1, stderr="Orca is not running")
        result = self.list_owned()
        self.assertEqual(result.returncode, 1)
        self.assertIn("List: could not read the worktrees of this repo from Orca", result.stdout)


if __name__ == "__main__":
    unittest.main()
