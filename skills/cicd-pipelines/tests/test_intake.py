"""Tests of scripts/intake.py through its command line, with a fake `gh` on PATH (see fake_gh.py)."""
import json
import os
import re
import unittest

from fake_gh import INTAKE, Sandbox
from skill_files import SKILL, read

KEYS = [
    "default_branch", "package_manager", "node_version_app", "engines", "scripts", "package_kind", "os_claims",
    "test_runners", "monorepo", "visibility", "runner_labels", "required_checks", "run_history",
    "existing_workflows", "installed_tools", "supported_node_majors",
    "environments", "plan", "rulesets", "classic_protection", "deploy_targets", "iac_tools", "aws_variables",
    "release_tool", "publish_target", "release_tag_pattern", "provenance", "deploy_history", "stack",
]
REPO = "repos/acme/widget"
PROTECTION = "repos/acme/widget/branches/main/protection/required_status_checks"
RULESETS = "repos/acme/widget/rules/branches/main"
RUNS = "repos/acme/widget/actions/workflows/ci.yml/runs?branch=main&status=success&per_page=10"
PUBLISH_SIGNALS = {
    "publishConfig": {"access": "public"}, "exports": "./index.js", "main": "index.js",
    "module": "index.mjs", "types": "index.d.ts", "bin": "cli.js", "files": ["dist"],
}
WORKFLOW = "name: CI\njobs:\n  test:\n    runs-on: {label}\n    steps:\n      - run: echo hi\n"
SCHEDULE = {
    "v18": {"start": "1999-01-01", "lts": "1999-06-01", "end": "1999-12-31"},
    "v22": {"start": "1999-01-01", "lts": "1999-06-01", "end": "2999-01-01"},
    "v23": {"start": "1999-01-01", "end": "2999-01-01"},
    "v24": {"start": "1999-01-01", "lts": "1999-06-01", "end": "2999-01-01"},
    "v99": {"start": "2999-01-01", "end": "2999-12-31"},
}


def job(name, seconds, conclusion="success"):
    return {"name": name, "conclusion": conclusion, "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T%02d:%02d:%02dZ" % (seconds // 3600, seconds % 3600 // 60, seconds % 60)}


class IntakeCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def facts(self, files, remote="https://github.com/acme/widget.git", **kwargs):
        return self.box.facts(self.box.repo(files, remote), **kwargs)

    def assertFact(self, fact, value, status):
        self.assertEqual((fact["value"], fact["status"]), (value, status), fact)


class Shape(IntakeCase):
    def test_the_output_has_the_29_facts_in_order_each_with_value_status_and_source(self):
        facts = self.facts({"package.json": {"name": "a"}})
        self.assertEqual(list(facts), KEYS)
        for key, fact in facts.items():
            self.assertEqual(sorted(fact), ["source", "status", "value"], key)
            self.assertIn(fact["status"], ("detected", "default", "unknown"), key)
            self.assertTrue(fact["source"], key)

    def test_a_repo_with_no_package_json_exits_0_with_empty_unknown_package_facts(self):
        facts = self.facts({".github/workflows/ci.yml": WORKFLOW.format(label="ubuntu-24.04")})
        self.assertFact(facts["engines"], [], "unknown")
        self.assertFact(facts["package_kind"], [], "unknown")
        self.assertFact(facts["os_claims"], ["linux"], "default")
        self.assertEqual(facts["existing_workflows"]["value"], [".github/workflows/ci.yml"])

    def test_every_gh_call_is_a_read_only_api_call(self):
        self.box.route(REPO, {"default_branch": "main", "private": False})
        self.facts({"package.json": {"name": "a"}, ".github/workflows/ci.yml": WORKFLOW.format(label="ubuntu-24.04")})
        calls = self.box.calls()
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call[0], "api", call)
            self.assertEqual(len(call), 2, call)
            for flag in ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"):
                self.assertNotIn(flag, call)

    def test_usage_errors_exit_2_with_nothing_on_stdout(self):
        repo = self.box.repo({"package.json": {}})
        for args in ([], [repo, repo], [os.path.join(repo, "package.json")]):
            done = self.box.run(*args)
            self.assertEqual(done.returncode, 2, args)
            self.assertEqual(done.stdout, "")
            self.assertTrue(done.stderr)


class PackageManager(IntakeCase):
    def manager(self, files):
        return self.facts(files)["package_manager"]

    def test_each_lockfile_names_its_manager(self):
        for lockfile, manager in (("pnpm-lock.yaml", "pnpm"), ("package-lock.json", "npm"), ("yarn.lock", "yarn")):
            self.assertFact(self.manager({"package.json": {}, lockfile: ""}),
                            {"manager": manager, "lockfile": lockfile}, "detected")

    def test_the_package_manager_field_without_a_lockfile_has_no_lockfile(self):
        self.assertFact(self.manager({"package.json": {"packageManager": "pnpm@9.1.0"}}),
                        {"manager": "pnpm", "lockfile": None}, "detected")

    def test_the_package_manager_field_wins_for_the_manager(self):
        self.assertFact(self.manager({"package.json": {"packageManager": "yarn@4.0.0"}, "package-lock.json": ""}),
                        {"manager": "yarn", "lockfile": "package-lock.json"}, "detected")

    def test_no_field_and_no_lockfile_is_unknown(self):
        self.assertFact(self.manager({"package.json": {}}), {"manager": None, "lockfile": None}, "unknown")


class NodeVersion(IntakeCase):
    def version(self, files):
        return self.facts(files)["node_version_app"]

    def test_nvmrc_comes_first_then_node_version_then_engines(self):
        both = {"package.json": {"engines": {"node": ">=20"}}, ".nvmrc": "v22.1.0\n", ".node-version": "20\n"}
        self.assertFact(self.version(both), "v22.1.0", "detected")
        del both[".nvmrc"]
        self.assertFact(self.version(both), "20", "detected")
        del both[".node-version"]
        self.assertFact(self.version(both), ">=20", "detected")

    def test_no_source_gives_the_newest_lts_of_the_offline_list(self):
        self.assertFact(self.version({"package.json": {}}), "26", "default")


class Packages(IntakeCase):
    def test_each_publish_signal_alone_makes_a_published_package(self):
        for key, value in PUBLISH_SIGNALS.items():
            kind = self.facts({"package.json": {"name": "a", key: value}})["package_kind"]
            self.assertEqual(kind["value"][0]["value"], "published", key)
            self.assertEqual(kind["status"], "detected", key)

    def test_no_signal_or_private_true_is_an_app(self):
        for package in ({"name": "a"}, {"name": "a", "private": True, "main": "x.js", "exports": "./x.js"}):
            self.assertEqual(self.facts({"package.json": package})["package_kind"]["value"][0]["value"], "app")

    def test_private_false_with_a_signal_is_published(self):
        kind = self.facts({"package.json": {"private": False, "main": "x.js"}})["package_kind"]
        self.assertEqual(kind["value"][0]["value"], "published")

    def test_an_invalid_package_json_is_a_default_app_and_the_default_engines(self):
        facts = self.facts({"package.json": "{ not json"})
        self.assertEqual(facts["package_kind"]["value"][0]["value"], "app")
        self.assertEqual(facts["package_kind"]["value"][0]["status"], "default")
        self.assertEqual(facts["package_kind"]["status"], "default")
        self.assertEqual(facts["engines"]["value"][0]["value"], "26")
        self.assertEqual(facts["os_claims"]["value"], ["linux"])

    def test_a_monorepo_has_one_entry_for_each_package_in_path_order(self):
        facts = self.facts({
            "package.json": {"private": True, "workspaces": ["packages/*"]},
            "packages/lib/package.json": {"name": "lib", "main": "i.js", "engines": {"node": ">=20"}},
            "packages/app/package.json": {"name": "app"},
            "packages/docs/readme.md": "no package here",
        })
        self.assertEqual([e["path"] for e in facts["package_kind"]["value"]], [".", "packages/app", "packages/lib"])
        self.assertEqual([e["value"] for e in facts["package_kind"]["value"]], ["app", "app", "published"])
        engines = {e["path"]: e for e in facts["engines"]["value"]}
        self.assertEqual((engines["packages/lib"]["value"], engines["packages/lib"]["status"]), (">=20", "detected"))
        self.assertEqual((engines["packages/app"]["value"], engines["packages/app"]["status"]), ("26", "default"))
        self.assertEqual(facts["engines"]["status"], "default")

    def test_the_workspaces_object_form_and_the_pnpm_file_find_packages(self):
        object_form = self.facts({"package.json": {"workspaces": {"packages": ["apps/*"]}},
                                  "apps/a/package.json": {"name": "a"}})
        self.assertEqual([e["path"] for e in object_form["package_kind"]["value"]], [".", "apps/a"])
        pnpm = self.facts({"package.json": {}, "pnpm-workspace.yaml": "packages:\n  - 'libs/*'\n  - '!libs/skip'\n",
                           "libs/a/package.json": {}, "libs/skip/package.json": {}})
        self.assertEqual([e["path"] for e in pnpm["package_kind"]["value"]], [".", "libs/a"])


class Scripts(IntakeCase):
    def scripts(self, files):
        return self.facts(files)["scripts"]

    def test_a_single_package_lists_the_names_of_its_scripts(self):
        fact = self.scripts({"package.json": {"scripts": {"lint": "eslint .", "test": "vitest run"}}})
        self.assertEqual(fact["status"], "detected")
        self.assertEqual(fact["value"], [{"path": ".", "value": ["lint", "test"], "status": "detected",
                                          "source": "./package.json scripts"}])

    def test_a_package_with_no_scripts_field_has_an_empty_detected_list(self):
        fact = self.scripts({"package.json": {"name": "a"}})
        self.assertEqual((fact["value"][0]["value"], fact["value"][0]["status"]), ([], "detected"))
        self.assertEqual(fact["status"], "detected")

    def test_a_monorepo_has_one_entry_for_each_package_in_path_order(self):
        fact = self.scripts({
            "package.json": {"workspaces": ["packages/*"], "scripts": {"build": "turbo run build"}},
            "packages/a/package.json": {"scripts": {"lint": "x"}},
            "packages/b/package.json": {"name": "b"},
        })
        self.assertEqual([(e["path"], e["value"]) for e in fact["value"]],
                         [(".", ["build"]), ("packages/a", ["lint"]), ("packages/b", [])])

    def test_an_unreadable_package_json_is_an_unknown_entry(self):
        fact = self.scripts({"package.json": "{ not json"})
        self.assertEqual((fact["value"][0]["value"], fact["value"][0]["status"]), ([], "unknown"))
        self.assertEqual(fact["status"], "unknown")

    def test_no_package_json_at_all_gives_an_empty_list_with_the_status_unknown(self):
        self.assertFact(self.scripts({"README.md": "x"}), [], "unknown")

    def test_a_scripts_field_of_the_wrong_shape_gives_an_empty_list(self):
        for value in ("lint", ["lint"], None, 3):
            fact = self.scripts({"package.json": {"scripts": value}})
            self.assertEqual(fact["value"][0]["value"], [], value)


class Comments(IntakeCase):
    def paths(self, workspace_yaml):
        facts = self.facts({"package.json": {}, "pnpm-workspace.yaml": workspace_yaml, "pkgs/a/package.json": {}})
        return [entry["path"] for entry in facts["package_kind"]["value"]]

    def test_a_trailing_comment_on_a_workspace_glob_or_header_is_ignored(self):
        self.assertEqual(self.paths("packages:\n  - 'pkgs/*'  # the packages\n"), [".", "pkgs/a"])
        self.assertEqual(self.paths("packages:  # list\n  - 'pkgs/*'\n"), [".", "pkgs/a"])

    def test_a_comment_line_inside_a_list_does_not_end_the_list(self):
        self.box.route(REPO, {"default_branch": "main", "private": True})
        files = {"package.json": {}, "pkgs/a/package.json": {}, "pkgs/b/package.json": {},
                 "pnpm-workspace.yaml": "packages:\n  - 'pkgs/a'\n# note\n  - 'pkgs/b'\n"}
        facts = self.facts(files)
        self.assertEqual([e["path"] for e in facts["package_kind"]["value"]], [".", "pkgs/a", "pkgs/b"])
        matrix = "    strategy:\n      matrix:\n        os:\n          - ubuntu-24.04\n# note\n          - windows-2022\n"
        workflow = {".github/workflows/ci.yml": WORKFLOW.format(label="${{ matrix.os }}") + matrix}
        labels = self.facts({"package.json": {}, **workflow})["runner_labels"]["value"]
        self.assertEqual(sorted(e["label"] for e in labels), ["ubuntu-24.04", "windows-2022"])

    def test_a_flow_style_packages_list_is_read(self):
        files = {"package.json": {}, "pkgs/a/package.json": {}, "pkgs/b/package.json": {},
                 "pnpm-workspace.yaml": "packages: [pkgs/a, 'pkgs/b']  # two\n"}
        facts = self.facts(files)
        self.assertEqual([e["path"] for e in facts["package_kind"]["value"]], [".", "pkgs/a", "pkgs/b"])

    def test_node_modules_and_folders_outside_the_repo_are_not_packages(self):
        os.makedirs(os.path.join(self.box.root, "outside", "pkg"))
        with open(os.path.join(self.box.root, "outside", "pkg", "package.json"), "w", encoding="utf-8") as handle:
            handle.write("{}")
        files = {"package.json": {}, "packages/a/package.json": {}, "node_modules/x/package.json": {},
                 "packages/a/node_modules/y/package.json": {},
                 "pnpm-workspace.yaml": "packages:\n  - '**'\n  - '../outside/*'\n"}
        facts = self.facts(files)
        self.assertEqual([e["path"] for e in facts["package_kind"]["value"]], [".", "packages/a"])

    def test_matrix_include_entries_are_runner_labels(self):
        matrix = ("    strategy:\n      matrix:\n        os: [ubuntu-latest, windows-latest]\n"
                  "        include:\n          - os: macos-latest\n")
        workflow = {".github/workflows/ci.yml": WORKFLOW.format(label="${{ matrix.os }}") + matrix}
        labels = self.facts({"package.json": {}, **workflow})["runner_labels"]["value"]
        self.assertEqual(sorted(e["label"] for e in labels), ["macos-latest", "ubuntu-latest", "windows-latest"])

    def test_a_trailing_comment_on_runs_on_is_ignored(self):
        files = {"package.json": {}, ".github/workflows/ci.yml": WORKFLOW.format(label="ubuntu-latest # note")}
        entry = self.facts(files)["runner_labels"]["value"][0]
        self.assertEqual((entry["label"], entry["kind"], entry["vcpus"]), ("ubuntu-latest", "standard", 2))

    def test_a_block_list_at_the_indent_of_the_key_is_read(self):
        text = "name: CI\njobs:\n  a:\n    runs-on:\n    - self-hosted\n    - windows-latest # win\n"
        labels = self.facts({".github/workflows/ci.yml": text})["runner_labels"]
        entries = {e["label"]: e["kind"] for e in labels["value"]}
        self.assertEqual(entries, {"self-hosted": "custom", "windows-latest": "standard"})
        self.assertEqual(labels["status"], "unknown")


class WrongShapes(IntakeCase):
    def history(self, runs, jobs):
        self.box.route(RUNS, {"workflow_runs": runs})
        for number in range(1, 11):
            self.box.route(f"repos/acme/widget/actions/runs/{number}/jobs?per_page=100", jobs)
        return self.facts({"package.json": {}})["run_history"]

    def test_wrong_shaped_answers_give_unknown_and_never_a_crash(self):
        ids = [{"id": n} for n in range(1, 11)]
        self.assertEqual(self.history(ids, [])["status"], "unknown")
        self.assertEqual(self.history(ids, {"jobs": [job("test", 1) | {"started_at": "bad"}]})["status"], "unknown")
        self.assertEqual(self.history(ids[:9] + [{}], {"jobs": []})["status"], "unknown")

    def test_a_check_name_that_is_not_a_string_is_unknown_not_a_crash(self):
        self.box.route(RULESETS, [])
        for contexts in (["a", None], ["a", ["b"]], [{"x": 1}]):
            self.box.route(PROTECTION, {"contexts": contexts, "checks": []})
            self.assertEqual(self.facts({"package.json": {}})["required_checks"]["status"], "unknown", contexts)

    def test_wrong_shaped_protection_or_rulesets_are_unknown_not_a_crash(self):
        self.box.route(PROTECTION, {"contexts": None, "checks": None})
        self.box.route(RULESETS, [])
        self.assertEqual(self.facts({"package.json": {}})["required_checks"]["status"], "unknown")
        self.box.route(PROTECTION, {"contexts": ["lint"], "checks": []})
        self.box.route(RULESETS, {"not": "a list"})
        self.assertEqual(self.facts({"package.json": {}})["required_checks"]["status"], "unknown")


class Monorepo(IntakeCase):
    def monorepo(self, files):
        return self.facts({"package.json": {}, **files})["monorepo"]

    def test_a_single_package_is_not_a_monorepo(self):
        self.assertFact(self.monorepo({}), {"monorepo": False, "tool": None}, "detected")

    def test_each_tool_is_detected(self):
        workspaces = {"package.json": {"workspaces": ["p/*"]}}
        cases = [
            ({"pnpm-workspace.yaml": "packages:\n  - 'p/*'\n"}, "pnpm"),
            (workspaces, "workspaces"),
            ({**workspaces, "turbo.json": "{}"}, "turbo"),
            ({**workspaces, "nx.json": "{}"}, "nx"),
            ({"pnpm-workspace.yaml": "packages:\n  - 'p/*'\n", "turbo.json": "{}"}, "turbo"),
            ({"pnpm-workspace.yaml": "packages:\n  - 'p/*'\n", "nx.json": "{}"}, "nx"),
            ({**workspaces, "turbo.json": "{}", "nx.json": "{}"}, "turbo"),
            ({**workspaces, "pnpm-workspace.yaml": "packages:\n  - 'p/*'\n"}, "pnpm"),
        ]
        for files, tool in cases:
            self.assertFact(self.monorepo(files), {"monorepo": True, "tool": tool}, "detected")


class OsAndRunners(IntakeCase):
    def test_os_claims_are_the_union_in_first_seen_order(self):
        facts = self.facts({
            "package.json": {"workspaces": ["p/*"], "os": ["linux", "darwin"]},
            "p/a/package.json": {"os": ["darwin", "win32"]},
        })
        self.assertFact(facts["os_claims"], ["linux", "darwin", "win32"], "detected")

    def test_test_runners_from_dependencies_and_config_files(self):
        facts = self.facts({
            "package.json": {"devDependencies": {"vitest": "^2", "@playwright/test": "^1"}, "dependencies": {}},
            "jest.config.js": "module.exports = {}",
        })
        self.assertFact(facts["test_runners"], ["@playwright/test", "jest", "vitest"], "detected")

    def test_no_test_runner_is_unknown(self):
        self.assertFact(self.facts({"package.json": {}})["test_runners"], [], "unknown")


class RunnerLabels(IntakeCase):
    def labels(self, files, private):
        self.box.route(REPO, {"default_branch": "main", "private": private})
        return self.facts({"package.json": {}, **files})["runner_labels"]

    def workflow(self, label, extra=""):
        return {".github/workflows/ci.yml": WORKFLOW.format(label=label) + extra}

    def test_a_standard_label_has_its_size_by_visibility(self):
        private = self.labels(self.workflow("ubuntu-24.04"), True)
        self.assertEqual(private["status"], "detected")
        self.assertEqual(private["value"][0]["kind"], "standard")
        self.assertEqual(private["value"][0]["vcpus"], 2)
        self.assertEqual(self.labels(self.workflow("ubuntu-24.04"), False)["value"][0]["vcpus"], 4)
        self.assertEqual(self.labels(self.workflow("macos-latest"), True)["value"][0]["vcpus"], 3)

    def test_a_self_hosted_label_is_custom_and_unknown(self):
        labels = self.labels(self.workflow("[self-hosted, linux]"), True)
        self.assertEqual(labels["status"], "unknown")
        entries = {e["label"]: e for e in labels["value"]}
        self.assertEqual((entries["self-hosted"]["kind"], entries["self-hosted"]["vcpus"],
                          entries["self-hosted"]["status"]), ("custom", None, "unknown"))

    def test_a_matrix_expression_resolves_from_a_literal_list(self):
        files = self.workflow("${{ matrix.os }}", "    strategy:\n      matrix:\n        os: [ubuntu-24.04, windows-2022]\n")
        labels = self.labels(files, True)
        self.assertEqual(sorted(e["label"] for e in labels["value"]), ["ubuntu-24.04", "windows-2022"])
        self.assertEqual(labels["status"], "detected")

    def test_an_expression_that_does_not_resolve_is_custom_and_unknown(self):
        labels = self.labels(self.workflow("${{ inputs.runner }}"), True)
        entry = labels["value"][0]
        self.assertEqual((entry["label"], entry["kind"], entry["vcpus"], entry["status"]),
                         ("${{ inputs.runner }}", "custom", None, "unknown"))
        self.assertEqual(labels["status"], "unknown")

    def test_a_larger_runner_label_is_custom_and_unknown(self):
        entry = self.labels(self.workflow("ubuntu-latest-8-cores"), True)["value"][0]
        self.assertEqual((entry["kind"], entry["status"]), ("custom", "unknown"))

    def test_no_workflow_means_no_label(self):
        self.assertFact(self.labels({}, True), [], "detected")


class GitHubFacts(IntakeCase):
    def test_default_branch_and_visibility_come_from_gh(self):
        self.box.route(REPO, {"default_branch": "trunk", "private": False})
        facts = self.facts({"package.json": {}})
        self.assertFact(facts["default_branch"], "trunk", "detected")
        self.assertFact(facts["visibility"], "public", "detected")

    def test_default_branch_falls_back_to_the_origin_head(self):
        repo = self.box.repo({"package.json": {}}, remote=None)
        self.box.git(repo, "remote", "add", "origin", "https://example.com/x/y.git")
        self.box.git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        self.assertFact(self.box.facts(repo)["default_branch"], "develop", "detected")

    def test_no_source_gives_main_and_private_defaults(self):
        facts = self.facts({"package.json": {}}, remote=None)
        self.assertFact(facts["default_branch"], "main", "default")
        self.assertFact(facts["visibility"], "private", "default")

    def test_the_three_url_forms_and_a_foreign_remote(self):
        self.box.route(REPO, {"default_branch": "trunk", "private": True})
        for remote in ("https://github.com/acme/widget", "git@github.com:acme/widget.git",
                       "ssh://git@github.com/acme/widget.git"):
            self.assertFact(self.facts({"package.json": {}}, remote=remote)["default_branch"], "trunk", "detected")
        foreign = self.facts({"package.json": {}}, remote="https://gitlab.com/acme/widget.git")
        self.assertFact(foreign["default_branch"], "main", "default")
        self.assertEqual(foreign["required_checks"]["status"], "unknown")
        self.assertIn("no GitHub remote", foreign["required_checks"]["source"])


class UnreadableInput(IntakeCase):
    def test_non_utf8_output_of_gh_makes_the_facts_that_need_it_unknown(self):
        self.box.raw_output("gh", b"\xff\xfe not utf-8")
        facts = self.facts({"package.json": {}})
        self.assertEqual(list(facts), KEYS)
        self.assertEqual((facts["required_checks"]["value"], facts["required_checks"]["status"]), (None, "unknown"))
        self.assertEqual((facts["run_history"]["value"], facts["run_history"]["status"]), (None, "unknown"))
        self.assertFact(facts["default_branch"], "main", "default")
        self.assertFact(facts["visibility"], "private", "default")

    def test_non_utf8_output_of_git_falls_back_to_the_default_branch(self):
        repo = self.box.repo({"package.json": {}}, remote=None)
        os.remove(os.path.join(self.box.bin, "git"))
        self.box.raw_output("git", b"origin/\xff\xfe\n")
        self.assertFact(self.box.facts(repo)["default_branch"], "main", "default")

    @unittest.skipIf(os.geteuid() == 0, "root reads every folder")
    def test_a_package_folder_without_read_permission_does_not_stop_the_script(self):
        repo = self.box.repo({"package.json": {"workspaces": ["packages/*"]}, "packages/a/package.json": {},
                              "jest.config.js": ""})
        folder = os.path.join(repo, "packages", "a")
        os.chmod(folder, 0o100)
        self.addCleanup(os.chmod, folder, 0o700)
        facts = self.box.facts(repo)
        self.assertFact(facts["test_runners"], ["jest"], "detected")


class RequiredChecks(IntakeCase):
    def checks(self, remote="https://github.com/acme/widget.git"):
        return self.facts({"package.json": {}}, remote=remote)["required_checks"]

    def test_protection_and_rulesets_are_merged_sorted_and_de_duplicated(self):
        self.box.route(PROTECTION, {"contexts": ["lint", "test"], "checks": [{"context": "test"}, {"context": "build"}]})
        self.box.route(RULESETS, [
            {"type": "required_status_checks",
             "parameters": {"required_status_checks": [{"context": "ci-passed"}, {"context": "lint"}]}},
            {"type": "pull_request", "parameters": {}},
        ])
        self.assertFact(self.checks(), ["build", "ci-passed", "lint", "test"], "detected")

    def test_a_branch_without_protection_is_readable_and_empty(self):
        self.box.route(PROTECTION, {"message": "Branch not protected"}, exit=1, stderr="gh: Branch not protected (HTTP 404)\n")
        self.box.route(RULESETS, [])
        self.assertFact(self.checks(), [], "detected")

    def test_an_unreadable_protection_is_unknown_with_the_reason(self):
        self.box.route(PROTECTION, {"message": "Forbidden"}, exit=1, stderr="gh: Resource not accessible (HTTP 403)\n")
        self.box.route(RULESETS, [])
        fact = self.checks()
        self.assertFact(fact, None, "unknown")
        self.assertIn("HTTP 403", fact["source"])

    def test_a_failed_rulesets_call_is_unknown(self):
        self.box.route(PROTECTION, {"contexts": ["lint"], "checks": []})
        self.assertFact(self.checks(), None, "unknown")

    def test_no_gh_on_path_is_unknown(self):
        self.box.cleanup()
        self.box = Sandbox(gh=False)
        self.addCleanup(self.box.cleanup)
        self.assertFact(self.checks(), None, "unknown")

    def test_no_github_remote_is_unknown(self):
        fact = self.checks(remote=None)
        self.assertFact(fact, None, "unknown")
        self.assertIn("no GitHub remote", fact["source"])


class RunHistory(IntakeCase):
    def history(self, runs=10, fail_jobs=False, missing_workflow=False):
        if not missing_workflow:
            self.box.route(RUNS, {"workflow_runs": [{"id": n} for n in range(1, runs + 1)]})
        for n in range(1, runs + 1):
            if fail_jobs and n == 3:
                continue
            self.box.route(f"repos/acme/widget/actions/runs/{n}/jobs?per_page=100",
                           {"jobs": [job("test", n * 60), job("lint", 100), job("flaky", 999, "failure")]})
        return self.facts({"package.json": {}})["run_history"]

    def test_ten_runs_give_the_median_of_each_job(self):
        fact = self.history()
        self.assertFact(fact, {"runs": 10, "jobs": {"test": {"median_seconds": 330}, "lint": {"median_seconds": 100}}},
                        "detected")

    def test_fewer_than_ten_runs_is_unknown(self):
        fact = self.history(runs=9)
        self.assertFact(fact, None, "unknown")
        self.assertIn("fewer than 10 successful runs", fact["source"])

    def test_a_failed_jobs_call_is_unknown(self):
        self.assertFact(self.history(fail_jobs=True), None, "unknown")

    def test_a_missing_ci_workflow_is_unknown(self):
        self.assertFact(self.history(missing_workflow=True), None, "unknown")


class NodeSchedule(IntakeCase):
    def write_schedule(self, schedule):
        path = os.path.join(self.box.root, "schedule.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(schedule, handle)
        return path

    def majors(self, **kwargs):
        return self.facts({"package.json": {}}, **kwargs)["supported_node_majors"]

    def test_offline_uses_the_dated_list_and_names_it(self):
        fact = self.majors()
        self.assertFact(fact, {"majors": [22, 24, 26], "newest_lts": 26}, "default")
        self.assertIn("offline list tools.md", fact["source"])
        self.assertIn("2026-11-09", fact["source"])

    def test_a_local_schedule_keeps_started_and_unexpired_majors(self):
        path = self.write_schedule(SCHEDULE)
        fact = self.majors(schedule=path)
        self.assertFact(fact, {"majors": [22, 23, 24], "newest_lts": 24}, "detected")
        self.assertIn(path, fact["source"])

    def test_the_local_schedule_wins_when_offline_is_also_set(self):
        path = self.write_schedule(SCHEDULE)
        self.assertEqual(self.majors(schedule=path, offline=True)["status"], "detected")

    def test_an_unreadable_schedule_falls_back_to_the_offline_list(self):
        fact = self.majors(schedule=os.path.join(self.box.root, "missing.json"))
        self.assertEqual(fact["status"], "default")
        self.assertIn("offline list tools.md", fact["source"])

    def test_a_schedule_with_no_lts_uses_the_highest_major(self):
        path = self.write_schedule({"v23": SCHEDULE["v23"]})
        self.assertFact(self.majors(schedule=path), {"majors": [23], "newest_lts": 23}, "detected")

    def test_the_offline_list_block_of_tools_md_has_its_three_fields(self):
        text = read(os.path.join(SKILL, "tools.md"))
        heading = text.index("## Offline Node support list")
        block = re.search(r"```json\n(.*?)\n```", text[heading:], re.S).group(1)
        data = json.loads(block)
        self.assertEqual(sorted(data), ["date", "majors", "newest_lts"])
        self.assertIn(data["newest_lts"], data["majors"])

    def test_the_old_list_file_is_gone_and_the_script_does_not_name_it(self):
        self.assertFalse(os.path.exists(os.path.join(SKILL, "scripts", "node-support-offline.json")))
        self.assertNotIn("node-support-offline", read(INTAKE))


class WorkflowsAndTools(IntakeCase):
    def test_both_workflow_extensions_are_listed_sorted(self):
        facts = self.facts({".github/workflows/b.yaml": "", ".github/workflows/a.yml": "", ".github/workflows/c.txt": ""})
        self.assertFact(facts["existing_workflows"], [".github/workflows/a.yml", ".github/workflows/b.yaml"], "detected")

    def test_no_workflow_folder_is_an_empty_detected_list(self):
        self.assertFact(self.facts({"package.json": {}})["existing_workflows"], [], "detected")

    def test_installed_tools_with_versions(self):
        self.box.tool("actionlint", "1.7.0")
        self.box.tool("zizmor", "zizmor 1.2.0", fail=True)
        tools = self.facts({"package.json": {}})["installed_tools"]
        self.assertEqual(tools["status"], "detected")
        self.assertEqual(tools["value"], {
            "actionlint": {"installed": True, "version": "1.7.0"},
            "zizmor": {"installed": True, "version": None},
            "pinact": {"installed": False, "version": None},
        })

    def test_all_three_tools_on_path_are_detected_with_their_versions(self):
        self.box.tool("actionlint", "1.7.0")
        self.box.tool("zizmor", "zizmor 1.2.0")
        self.box.tool("pinact", "pinact 3.0.0")
        tools = self.facts({"package.json": {}})["installed_tools"]
        self.assertEqual(tools["value"], {
            "actionlint": {"installed": True, "version": "1.7.0"},
            "zizmor": {"installed": True, "version": "zizmor 1.2.0"},
            "pinact": {"installed": True, "version": "pinact 3.0.0"},
        })

    def test_no_tool_on_path_is_detected_as_not_installed(self):
        tools = self.facts({"package.json": {}})["installed_tools"]
        self.assertEqual(tools["status"], "detected")
        self.assertEqual(tools["value"], {
            name: {"installed": False, "version": None} for name in ("actionlint", "zizmor", "pinact")})


ENVIRONMENTS = "repos/acme/widget/environments"
RULESET_LIST = "repos/acme/widget/rulesets"
CLASSIC = "repos/acme/widget/branches/main/protection"
DEPLOY_RUNS = "repos/acme/widget/actions/workflows/deploy.yml/runs?status=success&per_page=10"
FORBIDDEN = {"message": "Forbidden"}
FORBIDDEN_ERROR = "gh: Resource not accessible (HTTP 403)\n"


def environment(name, reviewers=False, timer=None, policy=None, bypass=True):
    rules = ([{"type": "required_reviewers", "reviewers": []}] if reviewers else []) + (
        [{"type": "wait_timer", "wait_timer": timer}] if timer is not None else [])
    return {"name": name, "can_admins_bypass": bypass, "protection_rules": rules, "deployment_branch_policy": policy}


def steps(*lines):
    """A deploy workflow file whose steps are the given lines (one `- <line>` each)."""
    return {".github/workflows/deploy.yml": "name: Deploy\njobs:\n  deploy:\n    runs-on: ubuntu-24.04\n    steps:\n"
            + "".join(f"      - {line}\n" for line in lines)}


class Environments(IntakeCase):
    def environments(self):
        return self.facts({"package.json": {}})["environments"]

    def test_each_environment_gives_its_five_fields(self):
        self.box.route(ENVIRONMENTS, {"total_count": 3, "environments": [
            environment("prod", reviewers=True, timer=30, policy={"protected_branches": False, "custom_branch_policies": True}),
            environment("staging", policy={"protected_branches": True, "custom_branch_policies": False}),
            environment("dev", bypass=False),
        ]})
        self.assertFact(self.environments(), [
            {"name": "prod", "reviewers": True, "wait_timer": 30, "branch_policy": "custom", "admin_bypass": True},
            {"name": "staging", "reviewers": False, "wait_timer": 0, "branch_policy": "protected_branches", "admin_bypass": True},
            {"name": "dev", "reviewers": False, "wait_timer": 0, "branch_policy": "none", "admin_bypass": False},
        ], "detected")

    def test_a_repo_with_no_environment_is_an_empty_detected_list(self):
        self.box.route(ENVIRONMENTS, {"total_count": 0, "environments": []})
        self.assertFact(self.environments(), [], "detected")

    def test_a_failed_call_is_an_empty_list_by_default_with_the_reason(self):
        self.box.route(ENVIRONMENTS, FORBIDDEN, exit=1, stderr=FORBIDDEN_ERROR)
        fact = self.environments()
        self.assertFact(fact, [], "default")
        self.assertIn("HTTP 403", fact["source"])

    def test_an_answer_without_the_environments_key_is_the_default(self):
        self.box.route(ENVIRONMENTS, {"total_count": 0})
        self.assertFact(self.environments(), [], "default")

    def test_no_github_remote_is_the_default(self):
        self.assertFact(self.facts({"package.json": {}}, remote=None)["environments"], [], "default")


class Plan(IntakeCase):
    def plan(self, repo_answer=None, remote="https://github.com/acme/widget.git"):
        if repo_answer is not None:
            self.box.route(REPO, repo_answer)
        return self.facts({"package.json": {}}, remote=remote)["plan"]

    def org_calls(self):
        return [call[1] for call in self.box.calls() if call[1].startswith("orgs/")]

    def assertProposed(self, fact):
        self.assertEqual(fact["status"], "default")
        self.assertIn("reviewers are proposed", fact["source"])
        self.assertIn("GitHub Enterprise", fact["source"])

    def test_a_public_repo_has_reviewers_and_makes_no_org_call(self):
        fact = self.plan({"default_branch": "main", "private": False, "owner": {"type": "Organization"}})
        self.assertFact(fact, {"visibility": "public", "plan": None, "reviewers_available": True}, "detected")
        self.assertEqual(self.org_calls(), [])

    def test_a_private_org_repo_on_the_team_plan_has_reviewers(self):
        self.box.route("orgs/acme", {"plan": {"name": "team"}})
        fact = self.plan({"default_branch": "main", "private": True, "owner": {"type": "Organization"}})
        self.assertFact(fact, {"visibility": "private", "plan": "team", "reviewers_available": True}, "detected")

    def test_a_private_org_repo_on_the_free_plan_has_no_reviewers(self):
        self.box.route("orgs/acme", {"plan": {"name": "free"}})
        fact = self.plan({"default_branch": "main", "private": True, "owner": {"type": "Organization"}})
        self.assertFact(fact, {"visibility": "private", "plan": "free", "reviewers_available": False}, "detected")

    def test_a_failed_org_call_proposes_reviewers_by_default(self):
        self.box.route("orgs/acme", FORBIDDEN, exit=1, stderr=FORBIDDEN_ERROR)
        fact = self.plan({"default_branch": "main", "private": True, "owner": {"type": "Organization"}})
        self.assertFact(fact, {"visibility": "private", "plan": None, "reviewers_available": True}, "default")
        self.assertProposed(fact)

    def test_an_org_answer_without_a_plan_is_the_same_as_a_failed_call(self):
        self.box.route("orgs/acme", {"login": "acme"})
        fact = self.plan({"default_branch": "main", "private": True, "owner": {"type": "Organization"}})
        self.assertFact(fact, {"visibility": "private", "plan": None, "reviewers_available": True}, "default")
        self.assertProposed(fact)

    def test_a_private_user_repo_makes_no_org_call(self):
        fact = self.plan({"default_branch": "main", "private": True, "owner": {"type": "User"}})
        self.assertFact(fact, {"visibility": "private", "plan": None, "reviewers_available": True}, "default")
        self.assertProposed(fact)
        self.assertEqual(self.org_calls(), [])

    def test_a_repo_answer_without_an_owner_is_a_user_repo(self):
        fact = self.plan({"default_branch": "main", "private": True})
        self.assertFact(fact, {"visibility": "private", "plan": None, "reviewers_available": True}, "default")
        self.assertEqual(self.org_calls(), [])

    def test_no_remote_or_an_unreadable_repo_answer_is_private_by_default(self):
        for fact in (self.plan(remote=None), self.plan()):
            self.assertFact(fact, {"visibility": "private", "plan": None, "reviewers_available": True}, "default")
            self.assertProposed(fact)
        self.assertEqual(self.org_calls(), [])


class Rulesets(IntakeCase):
    def rulesets(self):
        return self.facts({"package.json": {}})["rulesets"]

    def test_branch_and_tag_rulesets_are_listed(self):
        self.box.route(RULESET_LIST, [
            {"id": 1, "name": "main", "target": "branch", "enforcement": "active"},
            {"id": 2, "name": "tags", "target": "tag", "enforcement": "evaluate"},
        ])
        self.assertFact(self.rulesets(), [{"name": "main", "target": "branch", "enforcement": "active"},
                                          {"name": "tags", "target": "tag", "enforcement": "evaluate"}], "detected")

    def test_no_ruleset_is_an_empty_detected_list(self):
        self.box.route(RULESET_LIST, [])
        self.assertFact(self.rulesets(), [], "detected")

    def test_a_403_is_unknown_with_the_reason(self):
        self.box.route(RULESET_LIST, FORBIDDEN, exit=1, stderr=FORBIDDEN_ERROR)
        fact = self.rulesets()
        self.assertFact(fact, None, "unknown")
        self.assertIn("HTTP 403", fact["source"])

    def test_an_answer_that_is_not_a_list_or_has_incomplete_items_is_unknown(self):
        self.box.route(RULESET_LIST, {"message": "x"})
        self.assertFact(self.rulesets(), None, "unknown")
        self.box.route(RULESET_LIST, [{"name": "main"}])
        self.assertFact(self.rulesets(), None, "unknown")

    def test_no_remote_is_unknown(self):
        self.assertFact(self.facts({"package.json": {}}, remote=None)["rulesets"], None, "unknown")


class ClassicProtection(IntakeCase):
    def protection(self):
        return self.facts({"package.json": {}})["classic_protection"]

    def test_a_protected_branch_with_reviews_and_admin_enforcement(self):
        self.box.route(CLASSIC, {"required_pull_request_reviews": {}, "enforce_admins": {"enabled": True}})
        self.assertFact(self.protection(), {"branch": "main", "protected": True, "required_pull_request_reviews": True,
                                            "enforce_admins": True}, "detected")

    def test_a_protected_branch_without_reviews_or_admin_enforcement(self):
        self.box.route(CLASSIC, {"enforce_admins": {"enabled": False}})
        self.assertFact(self.protection(), {"branch": "main", "protected": True, "required_pull_request_reviews": False,
                                            "enforce_admins": False}, "detected")

    def test_a_branch_that_is_not_protected_is_all_false_and_detected(self):
        self.box.route(CLASSIC, {"message": "Branch not protected"}, exit=1, stderr="gh: Branch not protected (HTTP 404)\n")
        self.assertFact(self.protection(), {"branch": "main", "protected": False, "required_pull_request_reviews": False,
                                            "enforce_admins": False}, "detected")

    def test_a_403_and_a_wrong_shape_are_unknown(self):
        self.box.route(CLASSIC, FORBIDDEN, exit=1, stderr=FORBIDDEN_ERROR)
        fact = self.protection()
        self.assertFact(fact, None, "unknown")
        self.assertIn("HTTP 403", fact["source"])
        self.box.route(CLASSIC, {"required_pull_request_reviews": {}})
        self.assertFact(self.protection(), None, "unknown")

    def test_the_branch_name_is_quoted_in_the_path(self):
        self.box.route(REPO, {"default_branch": "release/1", "private": False})
        self.box.route("repos/acme/widget/branches/release%2F1/protection", {"enforce_admins": {"enabled": True}})
        fact = self.protection()
        self.assertEqual((fact["value"]["branch"], fact["status"]), ("release/1", "detected"))


TARGET_LINES = {
    "aws": "uses: aws-actions/configure-aws-credentials@v4",
    "s3": "run: aws s3 sync dist s3://bucket",
    "lambda": "run: aws lambda update-function-code --function-name f --zip-file fileb://f.zip",
    "ecs": "uses: aws-actions/amazon-ecs-deploy-task-definition@v2",
    "cloudfront": "run: aws cloudfront create-invalidation --distribution-id X --paths '/*'",
    "github-pages": "uses: actions/deploy-pages@v4",
    "cloudflare": "run: npx wrangler pages deploy dist",
    "vercel": "run: vercel --prod",
    "netlify": "run: netlify deploy --prod",
    "container-registry": "uses: docker/build-push-action@v6",
}
TOOL_LINES = {
    "terraform": "run: terraform apply -auto-approve",
    "opentofu": "uses: opentofu/setup-opentofu@v1",
    "cdk": "run: npx cdk deploy --all",
    "pulumi": "uses: pulumi/actions@v6",
    "serverless": "run: sls deploy",
    "sam": "run: sam deploy --no-confirm-changeset",
    "cloudformation": "run: aws cloudformation deploy --template-file t.yml --stack-name s",
}


class DeployTargetsAndIac(IntakeCase):
    def test_each_target_kind_is_found_through_its_pattern(self):
        for kind, line in TARGET_LINES.items():
            with self.subTest(kind):
                self.assertFact(self.facts(steps(line))["deploy_targets"], [kind], "detected")

    def test_each_iac_tool_is_found_through_its_pattern(self):
        for tool, line in TOOL_LINES.items():
            with self.subTest(tool):
                self.assertFact(self.facts(steps(line))["iac_tools"], [tool], "detected")

    def test_several_kinds_are_sorted(self):
        facts = self.facts(steps(TARGET_LINES["s3"], TARGET_LINES["aws"], TOOL_LINES["cdk"], TOOL_LINES["terraform"]))
        self.assertFact(facts["deploy_targets"], ["aws", "s3"], "detected")
        self.assertFact(facts["iac_tools"], ["cdk", "terraform"], "detected")

    def test_a_commented_pattern_is_not_found(self):
        facts = self.facts(steps("run: echo hi  # aws s3 sync and terraform apply", "# uses: actions/deploy-pages@v4"))
        self.assertFact(facts["deploy_targets"], [], "default")
        self.assertFact(facts["iac_tools"], [], "default")

    def test_a_pattern_must_end_at_a_word_edge(self):
        self.assertFact(self.facts(steps("run: pulumi update"))["iac_tools"], [], "default")

    def test_quotes_extra_spaces_and_a_ref_do_not_hide_a_pattern(self):
        facts = self.facts(steps("uses: 'actions/deploy-pages@abc123'", "run: aws   s3   cp a b"))
        self.assertFact(facts["deploy_targets"], ["github-pages", "s3"], "detected")

    def test_a_workflow_that_matches_nothing_and_no_workflow_are_defaults(self):
        for files in (steps("run: npm test"), {"package.json": {}}):
            facts = self.facts(files)
            self.assertFact(facts["deploy_targets"], [], "default")
            self.assertFact(facts["iac_tools"], [], "default")


AWS_STEP = ("uses: aws-actions/configure-aws-credentials@v4\n        with:\n          role-to-assume: {role}\n"
            "          aws-region: {region}")


class AwsVariables(IntakeCase):
    PLACEHOLDERS = {"role": ["vars.AWS_ROLE_<ENV>"], "region": ["vars.AWS_REGION"]}

    def aws(self, role, region):
        return self.facts(steps(AWS_STEP.format(role=role, region=region)))["aws_variables"]

    def test_names_of_vars_on_both_lines_are_detected(self):
        fact = self.aws("${{ vars.AWS_ROLE_PROD }}", "${{ vars.AWS_REGION_PROD }}")
        self.assertFact(fact, {"role": ["vars.AWS_ROLE_PROD"], "region": ["vars.AWS_REGION_PROD"]}, "detected")

    def test_a_literal_region_gives_the_region_placeholder_by_default(self):
        fact = self.aws("${{ vars.AWS_ROLE_PROD }}", "us-east-1")
        self.assertFact(fact, {"role": ["vars.AWS_ROLE_PROD"], "region": ["vars.AWS_REGION"]}, "default")
        self.assertIn("placeholder", fact["source"])
        self.assertIn("vars.AWS_REGION", fact["source"])

    def test_a_literal_arn_gives_the_role_placeholder_and_never_appears(self):
        arn = "arn:aws:iam::123456789012:role/deploy"
        files = steps(AWS_STEP.format(role=arn, region="eu-west-1"))
        fact = self.facts(files)["aws_variables"]
        self.assertFact(fact, self.PLACEHOLDERS, "default")
        done = self.box.run(self.box.repo(files))
        self.assertNotIn("123456789012", done.stdout)
        self.assertNotIn("eu-west-1", done.stdout)

    def test_only_the_vars_name_of_a_mixed_line_is_taken(self):
        fact = self.aws("${{ secrets.ROLE_ARN || vars.AWS_ROLE_DEV }}", "${{ vars.AWS_REGION }}")
        self.assertFact(fact, {"role": ["vars.AWS_ROLE_DEV"], "region": ["vars.AWS_REGION"]}, "detected")

    def test_a_secret_gives_no_name(self):
        self.assertFact(self.aws("${{ secrets.ROLE_ARN }}", "${{ vars.AWS_REGION }}"),
                        {"role": ["vars.AWS_ROLE_<ENV>"], "region": ["vars.AWS_REGION"]}, "default")

    def test_no_aws_step_gives_the_placeholders_and_no_gh_call_reads_a_variable(self):
        self.assertFact(self.facts({"package.json": {}})["aws_variables"], self.PLACEHOLDERS, "default")
        self.aws("${{ vars.A }}", "${{ vars.B }}")
        for call in self.box.calls():
            self.assertNotIn("variables", call[1])


class ReleaseTool(IntakeCase):
    def tool(self, files):
        return self.facts(files)["release_tool"]

    def test_each_tool_is_found_through_its_file(self):
        for tool, files in (("changesets", {".changeset/config.json": "{}"}),
                            ("release-please", {"release-please-config.json": "{}"}),
                            ("release-please", {".release-please-manifest.json": "{}"}),
                            ("semantic-release", {".releaserc.json": "{}"}),
                            ("semantic-release", {"release.config.js": ""}),
                            ("release-it", {".release-it.json": "{}"})):
            with self.subTest(tool, files=list(files)):
                self.assertFact(self.tool(files), [tool], "detected")

    def test_each_tool_is_found_through_its_dependency_in_either_section(self):
        for package in ("@changesets/cli", "release-please", "semantic-release", "release-it"):
            for section in ("dependencies", "devDependencies"):
                with self.subTest(package, section=section):
                    expected = "changesets" if package == "@changesets/cli" else package
                    self.assertFact(self.tool({"package.json": {section: {package: "1.0.0"}}}), [expected], "detected")

    def test_several_tools_are_sorted_and_none_is_the_default(self):
        self.assertFact(self.tool({".changeset/config.json": "{}", ".release-it.json": "{}"}),
                        ["changesets", "release-it"], "detected")
        self.assertFact(self.tool({"package.json": {}}), [], "default")


class PublishTarget(IntakeCase):
    def target(self, package, remote="https://github.com/acme/widget.git"):
        return self.facts({"package.json": package}, remote=remote)["publish_target"]

    def test_a_published_package_goes_to_npmjs(self):
        self.assertFact(self.target({"name": "a", "main": "index.js"}), ["npmjs"], "detected")

    def test_the_npm_registry_url_is_npmjs_with_or_without_a_slash(self):
        for registry in ("https://registry.npmjs.org", "https://registry.npmjs.org/"):
            self.assertFact(self.target({"name": "a", "publishConfig": {"registry": registry}}), ["npmjs"], "detected")

    def test_a_custom_registry_is_the_target(self):
        self.assertFact(self.target({"name": "a", "publishConfig": {"registry": "https://npm.pkg.github.com"}}),
                        ["https://npm.pkg.github.com"], "detected")

    def test_no_published_package_is_npmjs_by_default(self):
        self.assertFact(self.target({"name": "a", "private": True, "main": "x.js"}), ["npmjs"], "default")


class ReleaseTagPattern(IntakeCase):
    def pattern(self, tags):
        repo = self.box.repo({"package.json": {}})
        if tags:
            self.box.git(repo, "-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "--allow-empty", "-m", "x")
            for tag in tags:
                self.box.git(repo, "tag", tag)
        return self.box.facts(repo)["release_tag_pattern"]

    def test_each_tag_shape_gives_its_glob(self):
        self.assertFact(self.pattern(["v1.2.3", "v1.3.0-beta.1"]), "v*", "detected")
        self.assertFact(self.pattern(["1.0.0"]), "[0-9]*", "detected")
        self.assertFact(self.pattern(["pkg@1.0.0", "@scope/pkg@2.0.0"]), "*@*", "detected")

    def test_the_most_common_shape_wins_and_a_tie_takes_the_listed_order(self):
        self.assertFact(self.pattern(["v1.0.0", "1.0.0", "1.1.0"]), "[0-9]*", "detected")
        self.assertFact(self.pattern(["v1.0.0", "1.0.0"]), "v*", "detected")

    def test_no_tag_or_another_shape_only_is_the_default(self):
        self.assertFact(self.pattern([]), "v*", "default")
        self.assertFact(self.pattern(["latest"]), "v*", "default")

    def test_a_folder_that_is_not_a_git_repo_is_the_default(self):
        folder = os.path.join(self.box.root, "plain")
        os.mkdir(folder)
        self.assertFact(self.box.facts(folder)["release_tag_pattern"], "v*", "default")


class Provenance(IntakeCase):
    def provenance(self, package, private=False, readable=True):
        if readable:
            self.box.route(REPO, {"default_branch": "main", "private": private})
        return self.facts({"package.json": package})["provenance"]

    def test_a_public_package_of_a_public_repo_is_automatic(self):
        self.assertFact(self.provenance({"name": "pkg", "main": "x.js"}), True, "detected")
        self.assertFact(self.provenance({"name": "@s/pkg", "main": "x.js", "publishConfig": {"access": "public"}}),
                        True, "detected")

    def test_a_private_repo_is_not_automatic(self):
        self.assertFact(self.provenance({"name": "pkg", "main": "x.js"}, private=True), False, "detected")

    def test_a_package_that_is_not_public_is_not_automatic(self):
        for package in ({"name": "pkg", "main": "x.js", "private": True},
                        {"name": "@s/pkg", "main": "x.js"},
                        {"name": "pkg", "main": "x.js", "publishConfig": {"access": "restricted"}}):
            with self.subTest(package):
                self.assertFact(self.provenance(package), False, "detected")

    def test_no_published_package_is_false_and_detected(self):
        self.assertFact(self.provenance({"name": "app"}), False, "detected")

    def test_an_unreadable_visibility_is_false_by_default(self):
        self.assertFact(self.provenance({"name": "pkg", "main": "x.js"}, readable=False), False, "default")


class DeployHistory(IntakeCase):
    def history(self, runs=10, fail_jobs=False, extra_job_runs=()):
        self.box.route(DEPLOY_RUNS, {"workflow_runs": [{"id": n} for n in range(1, runs + 1)]})
        for n in range(1, runs + 1):
            if fail_jobs and n == 3:
                continue
            jobs = [job("deploy", n * 60), job("flaky", 999, "failure")]
            if n in extra_job_runs:
                jobs.append(job("smoke", n * 10))
            self.box.route(f"repos/acme/widget/actions/runs/{n}/jobs?per_page=100", {"jobs": jobs})
        return self.facts({"package.json": {}})

    def test_ten_runs_give_the_median_of_each_job_from_the_deploy_runs_path(self):
        facts = self.history()
        self.assertFact(facts["deploy_history"], {"runs": 10, "jobs": {"deploy": {"median_seconds": 330}}}, "detected")
        self.assertIn(["api", DEPLOY_RUNS], self.box.calls())

    def test_fewer_than_ten_runs_is_unknown(self):
        fact = self.history(runs=9)["deploy_history"]
        self.assertFact(fact, None, "unknown")
        self.assertIn("fewer than 10 successful runs of deploy.yml", fact["source"])

    def test_a_failed_jobs_call_is_unknown(self):
        self.assertFact(self.history(fail_jobs=True)["deploy_history"], None, "unknown")

    def test_an_answer_without_the_workflow_runs_key_is_unknown(self):
        self.box.route(DEPLOY_RUNS, {"total_count": 0})
        self.assertFact(self.facts({"package.json": {}})["deploy_history"], None, "unknown")

    def test_a_job_that_succeeds_in_only_some_runs_has_the_median_of_those_runs(self):
        jobs = self.history(extra_job_runs=(2, 4, 6))["deploy_history"]["value"]["jobs"]
        self.assertEqual(jobs["smoke"], {"median_seconds": 40})

    def test_the_two_histories_read_their_own_workflow_only(self):
        facts = self.history()
        self.assertFact(facts["run_history"], None, "unknown")
        self.box.route(DEPLOY_RUNS, {"message": "gone"}, exit=1, stderr="gh: Not Found (HTTP 404)\n")
        self.box.route(RUNS, {"workflow_runs": [{"id": n} for n in range(1, 11)]})
        facts = self.facts({"package.json": {}})
        self.assertFact(facts["deploy_history"], None, "unknown")
        self.assertEqual(facts["run_history"]["status"], "detected")


class UnreadableCdFacts(IntakeCase):
    def test_non_utf8_output_of_gh_leaves_each_new_gh_fact_at_its_default(self):
        self.box.raw_output("gh", b"\xff\xfe not utf-8")
        facts = self.facts({"package.json": {}})
        self.assertFact(facts["environments"], [], "default")
        self.assertEqual(facts["plan"]["status"], "default")
        for name in ("rulesets", "classic_protection", "deploy_history"):
            self.assertFact(facts[name], None, "unknown")


class Stack(IntakeCase):
    def stack(self, files, links=()):
        """The `stack` fact of a repo with `files`, after `links` (pairs of target and link path) are made."""
        path = self.box.repo(files)
        for target, name in links:
            os.makedirs(os.path.dirname(os.path.join(path, name)), exist_ok=True)
            os.symlink(target, os.path.join(path, name))
        return self.box.facts(path)["stack"]

    def assertStack(self, fact, languages, ci_systems, status):
        self.assertEqual(fact["value"], {
            "languages": [{"item": item, "file": file} for item, file in languages],
            "ci_systems": [{"item": item, "file": file} for item, file in ci_systems],
        })
        self.assertEqual(fact["status"], status)
        self.assertTrue(fact["source"])

    def test_node_typescript_with_no_ci_file(self):
        self.assertStack(self.stack({"package.json": {}}), [("Node/TypeScript", "package.json")], [], "detected")

    def test_node_typescript_on_gitlab_ci(self):
        fact = self.stack({"package.json": {}, ".gitlab-ci.yml": "stages: []\n"})
        self.assertStack(fact, [("Node/TypeScript", "package.json")], [("GitLab CI", ".gitlab-ci.yml")], "detected")

    def test_rust_on_github_actions(self):
        fact = self.stack({"Cargo.toml": "", ".github/workflows/ci.yml": WORKFLOW.format(label="ubuntu-24.04")})
        self.assertStack(fact, [("Rust", "Cargo.toml")], [("GitHub Actions", ".github/workflows/ci.yml")], "detected")

    def test_go_on_gitlab_ci(self):
        fact = self.stack({"go.mod": "", ".gitlab-ci.yml": ""})
        self.assertStack(fact, [("Go", "go.mod")], [("GitLab CI", ".gitlab-ci.yml")], "detected")

    def test_a_mixed_repo_lists_both_languages_in_table_order(self):
        fact = self.stack({"Cargo.toml": "", "package.json": {}})
        self.assertStack(fact, [("Node/TypeScript", "package.json"), ("Rust", "Cargo.toml")], [], "detected")

    def test_node_typescript_on_github_actions(self):
        fact = self.stack({"package.json": {}, ".github/workflows/ci.yml": WORKFLOW.format(label="ubuntu-24.04")})
        self.assertStack(fact, [("Node/TypeScript", "package.json")],
                         [("GitHub Actions", ".github/workflows/ci.yml")], "detected")

    def test_an_empty_repo_is_unknown_with_two_empty_lists(self):
        self.assertStack(self.stack({}), [], [], "unknown")

    def test_a_manifest_at_depth_2_is_found_and_at_depth_3_is_not(self):
        self.assertStack(self.stack({"a/b/go.mod": ""}), [("Go", "a/b/go.mod")], [], "detected")
        self.assertStack(self.stack({"a/b/c/go.mod": ""}), [], [], "unknown")

    def test_a_skipped_folder_hides_its_manifest(self):
        for folder in ("node_modules", "vendor", "target", ".git"):
            self.assertStack(self.stack({f"{folder}/Cargo.toml": ""}), [], [], "unknown")

    def test_a_symbolic_link_to_a_folder_is_not_entered(self):
        path = self.box.repo({"a/b/c/package.json": {}})
        os.symlink(os.path.join(path, "a", "b", "c"), os.path.join(path, "linked"))
        self.assertStack(self.box.facts(path)["stack"], [], [], "unknown")

    def test_a_symbolic_link_is_not_a_manifest_or_a_ci_file(self):
        fact = self.stack({"other.txt": ""}, links=[("other.txt", "package.json"), ("other.txt", ".github/workflows/ci.yml")])
        self.assertStack(fact, [], [], "unknown")

    def test_a_csproj_file_gives_dot_net(self):
        self.assertStack(self.stack({"src/App.csproj": ""}), [(".NET", "src/App.csproj")], [], "detected")

    def test_the_entry_names_the_shallowest_file_and_a_tie_the_first_path(self):
        fact = self.stack({"a/b/pyproject.toml": "", "requirements.txt": "", "z/setup.py": "", "m/setup.py": ""})
        self.assertStack(fact, [("Python", "requirements.txt")], [], "detected")
        fact = self.stack({"z/Gemfile": "", "m/Gemfile": ""})
        self.assertStack(fact, [("Ruby", "m/Gemfile")], [], "detected")

    def test_file_names_match_exactly_with_their_case(self):
        self.assertStack(self.stack({"gemfile": ""}), [], [], "unknown")

    def test_each_table_row_is_detected(self):
        fact = self.stack({"pom.xml": "", "composer.json": "", "Jenkinsfile": "", ".circleci/config.yml": "",
                           "azure-pipelines.yml": "", "bitbucket-pipelines.yml": "", ".travis.yml": "",
                           ".gitlab-ci.yml": "", ".github/workflows/b.yaml": "", ".github/workflows/a.yml": ""})
        self.assertStack(
            fact, [("JVM", "pom.xml"), ("PHP", "composer.json")],
            [("GitHub Actions", ".github/workflows/a.yml"), ("GitLab CI", ".gitlab-ci.yml"),
             ("Jenkins", "Jenkinsfile"), ("CircleCI", ".circleci/config.yml"),
             ("Azure Pipelines", "azure-pipelines.yml"), ("Bitbucket Pipelines", "bitbucket-pipelines.yml"),
             ("Travis CI", ".travis.yml")], "detected")

    def test_a_ci_file_in_a_sub_folder_is_not_detected(self):
        self.assertStack(self.stack({"sub/.gitlab-ci.yml": ""}), [], [], "unknown")

    def test_a_yaml_workflow_is_detected_and_a_folder_named_yml_is_not(self):
        fact = self.stack({".github/workflows/ci.yaml": "", ".github/workflows/x.yml/keep.txt": ""})
        self.assertStack(fact, [], [("GitHub Actions", ".github/workflows/ci.yaml")], "detected")

    def test_the_existing_workflows_fact_does_not_change(self):
        path = self.box.repo({"other.txt": ""})
        os.makedirs(os.path.join(path, ".github", "workflows"))
        os.symlink(os.path.join(path, "other.txt"), os.path.join(path, ".github", "workflows", "ci.yml"))
        facts = self.box.facts(path)
        self.assertEqual(facts["existing_workflows"]["value"], [".github/workflows/ci.yml"])
        self.assertStack(facts["stack"], [], [], "unknown")


if __name__ == "__main__":
    unittest.main()
