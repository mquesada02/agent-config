import json
import os
import unittest

from cleanup_support import CleanupCase, git

SUB = "sub"


class SubmoduleCase(CleanupCase):
    """A worktree with an initialized submodule whose commit is on the submodule's remote."""

    def setUp(self):
        super().setUp()
        self.sub_remote = os.path.join(self.root, "subremote.git")
        seed = os.path.join(self.root, "subseed")
        git("init", "-q", "--bare", "-b", "main", self.sub_remote, env=self.env)
        git("clone", "-q", self.sub_remote, seed, env=self.env)
        git("checkout", "-q", "-b", "main", cwd=seed, env=self.env)
        self.commit(seed, "sub.txt")
        git("push", "-q", "-u", "origin", "main", cwd=seed, env=self.env)
        git("-c", "protocol.file.allow=always", "submodule", "add", "-q", self.sub_remote, SUB, cwd=self.wt, env=self.env)
        self.sub = os.path.join(self.wt, SUB)
        self.record_gitlink()

    def record_gitlink(self):
        """Commit and push the worktree, so that its tip moves and checks 3, 5 and 6 still pass."""
        git("add", "-A", cwd=self.wt, env=self.env)
        git("commit", "-q", "-m", "gitlink", cwd=self.wt, env=self.env)
        git("push", "-q", "origin", self.BRANCH, cwd=self.wt, env=self.env)
        self.tip = self.git_out(self.wt, "rev-parse", "HEAD")
        self.stub_gh_merged()

    def assert_submodule_refusal(self, result, path=SUB):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = self.starts(result, "Submodules pushed")
        self.assertEqual(len(lines), 1)
        self.assertIn(f": {path}:", lines[0])
        self.assert_unchanged()


class SubmodulesPushedTest(SubmoduleCase):
    def test_a_pushed_submodule_commit_passes(self):
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.starts(result, "Submodules pushed"))

    def test_a_worktree_without_submodules_passes(self):
        git("rm", "-q", "-f", SUB, cwd=self.wt, env=self.env)
        self.record_gitlink()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_submodule_commit_on_no_remote_branch_refuses(self):
        self.commit(self.sub, "local.txt")
        self.record_gitlink()
        self.assert_submodule_refusal(self.run_cleanup(self.wt))

    def test_a_failed_fetch_refuses(self):
        git("remote", "set-url", "origin", os.path.join(self.root, "missing.git"), cwd=self.sub, env=self.env)
        self.assert_submodule_refusal(self.run_cleanup(self.wt))

    def test_a_submodule_with_no_remote_refuses(self):
        git("remote", "remove", "origin", cwd=self.sub, env=self.env)
        self.assert_submodule_refusal(self.run_cleanup(self.wt))

    def test_a_submodule_folder_with_a_git_entry_and_no_commit_refuses(self):
        empty = os.path.join(self.wt, "empty")
        os.mkdir(empty)
        git("init", "-q", empty, env=self.env)
        git("update-index", "--add", "--cacheinfo", f"160000,{self.tip},empty", cwd=self.wt, env=self.env)
        self.record_gitlink()
        self.assert_submodule_refusal(self.run_cleanup(self.wt), "empty")

    def test_an_uninitialized_submodule_is_skipped(self):
        os.mkdir(os.path.join(self.wt, "ghost"))
        git("update-index", "--add", "--cacheinfo", f"160000,{self.tip},ghost", cwd=self.wt, env=self.env)
        self.record_gitlink()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.starts(result, "Submodules pushed"))

    def test_each_failing_submodule_gets_one_line(self):
        git("remote", "set-url", "origin", os.path.join(self.root, "missing.git"), cwd=self.sub, env=self.env)
        second = os.path.join(self.wt, "second")
        git("-c", "protocol.file.allow=always", "submodule", "add", "-q", self.sub_remote, "second", cwd=self.wt, env=self.env)
        self.commit(second, "local.txt")
        self.record_gitlink()
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        lines = self.starts(result, "Submodules pushed")
        self.assertEqual(len(lines), 2)
        self.assertEqual(sorted(path for path in (SUB, "second") for line in lines if f": {path}:" in line), ["second", SUB])

    def test_skip_ownership_does_not_skip_the_check(self):
        self.commit(self.sub, "local.txt")
        self.record_gitlink()
        self.assert_submodule_refusal(self.run_cleanup("--skip-ownership", self.wt))


class DockerTest(CleanupCase):
    def stub_stacks(self, *stacks):
        self.stub("docker compose ls", json.dumps(list(stacks)))

    def stack(self, name, *files):
        return {"Name": name, "Status": "running(1)", "ConfigFiles": ",".join(files)}

    def assert_docker_refusal(self, result, *names):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = self.starts(result, "Docker")
        self.assertEqual(len(lines), len(names))
        for name in names:
            self.assertEqual(len([line for line in lines if name in line]), 1, name)
        self.assert_unchanged()

    def docker_calls(self):
        return [c for c in self.calls() if c.startswith("docker")]

    def test_no_docker_on_the_path_passes(self):
        result = self.run_cleanup(self.wt, no_docker=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.starts(result, "Docker"))
        self.assertEqual(self.docker_calls(), [])

    def test_an_empty_stack_list_passes(self):
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.docker_calls(), ["docker compose ls -a --format json"])

    def test_a_failing_docker_compose_ls_refuses(self):
        self.stub("docker compose ls", rc=1, stderr="Cannot connect to the Docker daemon")
        self.assert_docker_refusal(self.run_cleanup(self.wt), "compose ls")

    def test_output_that_is_not_json_refuses(self):
        self.stub("docker compose ls", "not json")
        self.assert_docker_refusal(self.run_cleanup(self.wt), "compose ls")

    def test_a_json_object_instead_of_a_list_refuses(self):
        self.stub("docker compose ls", "{}")
        self.assert_docker_refusal(self.run_cleanup(self.wt), "compose ls")

    def test_a_stack_with_a_config_file_in_the_target_refuses_and_is_named(self):
        self.stub_stacks(self.stack("app", os.path.join(self.wt, "compose.yml")))
        self.assert_docker_refusal(self.run_cleanup(self.wt), "app")

    def test_each_stack_in_the_target_is_named(self):
        self.stub_stacks(self.stack("one", os.path.join(self.wt, "a.yml")),
                         self.stack("two", os.path.join(self.root, "elsewhere", "b.yml"), os.path.join(self.wt, "sub", "b.yml")),
                         self.stack("three", os.path.join(self.root, "elsewhere", "c.yml")))
        self.assert_docker_refusal(self.run_cleanup(self.wt), "one", "two")

    def test_stacks_elsewhere_pass(self):
        self.stub_stacks(self.stack("other", os.path.join(self.root, "elsewhere", "compose.yml")))
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_sibling_folder_with_the_same_prefix_is_not_inside(self):
        self.stub_stacks(self.stack("sibling", self.wt + "-2/compose.yml"))
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_a_config_file_that_does_not_exist_inside_the_target_refuses(self):
        self.stub_stacks(self.stack("gone", os.path.join(self.wt, "deleted", "compose.yml")))
        self.assert_docker_refusal(self.run_cleanup(self.wt), "gone")

    def test_a_symlinked_config_path_is_compared_by_its_real_path(self):
        link = os.path.join(self.root, "link")
        os.symlink(self.wt, link)
        self.stub_stacks(self.stack("linked", os.path.join(link, "compose.yml")))
        self.assert_docker_refusal(self.run_cleanup(self.wt), "linked")

    def test_a_relative_config_file_path_passes(self):
        self.stub_stacks(self.stack("relative", os.path.join(os.path.basename(self.wt), "compose.yml")))
        result = self.run_cleanup(self.wt, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_an_entry_without_config_files_passes(self):
        self.stub_stacks({"Name": "bare"})
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)

    def test_an_entry_without_a_name_but_with_a_config_file_in_the_target_refuses(self):
        self.stub_stacks({"ConfigFiles": os.path.join(self.wt, "compose.yml")})
        self.assert_docker_refusal(self.run_cleanup(self.wt), "(unnamed)")

    def test_skip_ownership_does_not_skip_the_check(self):
        self.stub_show()
        self.stub_stacks(self.stack("app", os.path.join(self.wt, "compose.yml")))
        self.assert_docker_refusal(self.run_cleanup("--skip-ownership", self.wt), "app")

    def test_the_command_never_runs_docker_compose_down(self):
        self.stub_stacks(self.stack("app", os.path.join(self.wt, "compose.yml")))
        self.run_cleanup(self.wt)
        self.assertEqual(self.docker_calls(), ["docker compose ls -a --format json"])
        self.stub_stacks()
        self.assertEqual(self.run_cleanup(self.wt).returncode, 0)
        self.assertFalse([c for c in self.docker_calls() if " down" in c])


class RefusalListTest(SubmoduleCase):
    def test_both_refusals_join_the_list_in_check_order_and_nothing_changes(self):
        git("remote", "set-url", "origin", os.path.join(self.root, "missing.git"), cwd=self.sub, env=self.env)
        with open(os.path.join(self.wt, "new.txt"), "w") as f:
            f.write("x")
        self.stub("docker compose ls", json.dumps([{"Name": "app", "ConfigFiles": os.path.join(self.wt, "compose.yml")}]))
        result = self.run_cleanup(self.wt)
        self.assertEqual(result.returncode, 1)
        names = [line.split(":")[0] for line in self.lines(result)]
        self.assertEqual([n for n in names if n in ("Clean", "Submodules pushed", "Docker")],
                         ["Clean", "Submodules pushed", "Docker"])
        self.assert_unchanged()
        self.assertEqual(os.listdir(self.wt).count("new.txt"), 1)


if __name__ == "__main__":
    unittest.main()
