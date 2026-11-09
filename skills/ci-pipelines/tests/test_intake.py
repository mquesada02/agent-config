"""Tests of scripts/intake.py through its command line, with a fake `gh` on PATH (see fake_gh.py)."""
import json
import os
import unittest

from fake_gh import Sandbox
from skill_files import SKILL, read

KEYS = [
    "default_branch", "package_manager", "node_version_app", "engines", "package_kind", "os_claims",
    "test_runners", "monorepo", "visibility", "runner_labels", "required_checks", "run_history",
    "existing_workflows", "installed_tools", "supported_node_majors",
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
    def test_the_output_has_the_15_facts_in_order_each_with_value_status_and_source(self):
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
        self.assertIn("scripts/node-support-offline.json", fact["source"])
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
        self.assertIn("scripts/node-support-offline.json", fact["source"])

    def test_a_schedule_with_no_lts_uses_the_highest_major(self):
        path = self.write_schedule({"v23": SCHEDULE["v23"]})
        self.assertFact(self.majors(schedule=path), {"majors": [23], "newest_lts": 23}, "detected")

    def test_the_offline_list_file_has_its_three_fields(self):
        data = json.loads(read(os.path.join(SKILL, "scripts", "node-support-offline.json")))
        self.assertEqual(sorted(data), ["date", "majors", "newest_lts"])
        self.assertIn(data["newest_lts"], data["majors"])


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


if __name__ == "__main__":
    unittest.main()
