"""Tests of scripts/check_workflow.py (the structural assertion script) through its command line."""
import os
import subprocess
import sys
import unittest

from skill_files import SKILL, all_rules, read

SCRIPT = os.path.join(SKILL, "scripts", "check_workflow.py")
SINGLE = os.path.join(SKILL, "templates", "single-package.yml")
MONO = os.path.join(SKILL, "templates", "monorepo.yml")
# The assertions that apply to every written ci.yml (the applicability paragraph of the spec).
COMMON = [
    "name=CI", "job=changes,lint,typecheck,test,build,audit,ci-passed", "triggers", "concurrency", "permissions",
    "pinned-uses", "persist-credentials", "pinned-runners", "no-run-expr", "named-run-steps", "short-run-blocks",
    "short-comments", "timeouts", "timeout=changes:5", "timeout=ci-passed:5", "timeout=lint:10",
    "timeout=typecheck:10", "timeout=build:10", "timeout=audit:10", "timeout=test:15", "gate", "changes", "fail-fast",
    "matrix-node=26", "matrix-only-test", "matrix-name", "no-shards", "audit-job", "no-privileged-trigger",
    "no-needs-between", "job-names", "no-text=secrets: inherit", "no-text=node_modules",
]
SINGLE_ONLY = ["checkout-depth=default", "install=npm ci"]
MONO_ONLY = ["affected-run=turbo", "install=npm ci"]
# The rule coverage table of the spec: rule ids and the assertion names that expect them.
COVERAGE = {
    ("NAME-01", "NAME-02"): "name", ("NAME-03",): "job", ("NAME-04",): "job-names", ("NAME-05",): "matrix-name",
    ("NAME-06", "NAME-07"): "named-run-steps", ("NAME-08",): "gate", ("GRAPH-01", "GRAPH-02"): "no-needs-between",
    ("GRAPH-03",): "matrix-only-test", ("GRAPH-04",): "fail-fast", ("GRAPH-05",): "no-shards",
    ("COST-01", "COST-03"): "triggers", ("COST-02",): "concurrency", ("COST-04",): "timeouts",
    ("COST-05",): "install", ("COST-06",): "workers", ("COST-07",): "pinned-runners",
    ("COST-08",): "checkout-depth", ("MONO-01", "MONO-02"): "affected-run", ("SEC-01",): "pinned-uses",
    ("SEC-02",): "dependabot", ("SEC-03",): "permissions", ("SEC-04",): "no-run-expr",
    ("SEC-05",): "persist-credentials", ("SEC-07", "SEC-09"): "no-privileged-trigger",
    ("SEC-08",): "no-text", ("SEC-10",): "audit-job", ("MAINT-01",): "short-run-blocks",
    ("MAINT-02",): "short-comments",
}
NOT_CLAIMED = {"SEC-06", "GRAPH-06", "GRAPH-07", "MAINT-03", "NAME-09"}


def run(text, *asserts):
    done = subprocess.run([sys.executable, "-I", SCRIPT, "-", "--assert", *asserts], input=text,
                          capture_output=True, text=True)
    return done.returncode, done.stdout.splitlines(), done.stderr


def failed(text, assertion):
    """The FAIL lines of one assertion on a text."""
    code, lines, _ = run(text, assertion)
    assert code == 1, (assertion, code, lines)
    return [line for line in lines if line.startswith("FAIL ") and line != "FAIL"]


class Templates(unittest.TestCase):
    def test_the_single_package_template_passes_its_assertions(self):
        code, lines, _ = run(read(SINGLE), *COMMON, *SINGLE_ONLY)
        self.assertEqual((code, lines), (0, ["PASS"]))

    def test_the_monorepo_template_passes_its_assertions(self):
        code, lines, _ = run(read(MONO), *COMMON, *MONO_ONLY)
        self.assertEqual((code, lines), (0, ["PASS"]))

    def test_the_templates_hold_no_fill_comment_and_no_shard(self):
        for path in (SINGLE, MONO):
            text = read(path)
            self.assertNotIn("fill", text.lower())
            self.assertNotIn("shard", text.lower())


class Breakers(unittest.TestCase):
    """A change that breaks one rule makes its assertion fail and names the assertion."""

    def breaks(self, assertion, old, new, path=SINGLE, count=1):
        text = read(path)
        self.assertIn(old, text)
        lines = failed(text.replace(old, new, count), assertion)
        self.assertTrue(lines, assertion)
        self.assertTrue(all(line.startswith(f"FAIL {assertion.split('=')[0]}") for line in lines), lines)

    def test_the_name(self):
        self.breaks("name=CI", "name: CI\non:", "name: Build\non:")

    def test_a_missing_job(self):
        self.breaks("job=lint", "  lint:\n", "  linting:\n")

    def test_a_job_that_must_be_absent(self):
        self.assertTrue(failed(read(SINGLE), "no-job=lint"))
        self.assertEqual(run(read(SINGLE), "no-job=deploy")[0], 0)

    def test_the_triggers(self):
        self.breaks("triggers", "    branches: [main]\n", "")
        self.breaks("triggers", "  pull_request:\n", "  pull_request:\n    paths-ignore: ['docs/**']\n")

    def test_the_concurrency_block(self):
        self.breaks("concurrency", "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
                    "cancel-in-progress: true")

    def test_the_permissions(self):
        self.breaks("permissions", "permissions:\n  contents: read\njobs:", "jobs:")
        self.breaks("permissions", "permissions:\n  contents: read\njobs:",
                    "permissions:\n  contents: write\njobs:")

    def test_a_tag_pin(self):
        self.breaks("pinned-uses", "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0",
                    "actions/setup-node@v7")
        self.breaks("pinned-uses", "# v7.1.0", "# release", count=1)

    def test_persist_credentials(self):
        self.breaks("persist-credentials", "          persist-credentials: false\n", "", count=1)

    def test_a_floating_runner(self):
        self.breaks("pinned-runners", "runs-on: ubuntu-24.04", "runs-on: ubuntu-latest")

    def test_an_expression_in_a_run_block(self):
        self.breaks("no-run-expr", "run: npm run lint", "run: npm run lint ${{ github.head_ref }}")

    def test_an_unnamed_or_long_or_ticketed_run_step(self):
        self.breaks("named-run-steps", "      - name: Run lint\n        run:", "      - run:")
        self.breaks("named-run-steps", "name: Run lint", "name: " + "x" * 51)
        self.breaks("named-run-steps", "name: Run lint", "name: Run lint (see #123)")

    def test_a_long_run_block_and_a_long_comment(self):
        self.breaks("short-run-blocks", "        run: npm run lint\n",
                    "        run: |\n" + "".join(f"          echo {i}\n" for i in range(11)))
        self.breaks("short-comments", "  lint:\n", "  # a\n  # b\n  # c\n  # d\n  lint:\n")

    def test_a_missing_or_wrong_timeout(self):
        self.breaks("timeouts", "    timeout-minutes: 10\n", "", count=1)
        self.breaks("timeout=test:15", "timeout-minutes: 15", "timeout-minutes: 30")

    def test_the_gate(self):
        self.breaks("gate", "    if: always()\n", "")
        self.breaks("gate", "needs: [changes, lint, typecheck, test, build, audit]",
                    "needs: [changes, lint, typecheck, test, build]")
        self.breaks("gate", "name: CI passed", "name: Done")

    def test_the_changes_job(self):
        self.breaks("changes", "    if: needs.changes.outputs.code == 'true'\n", "", count=1)
        self.breaks("changes", "      pull-requests: read\n", "")

    def test_fail_fast(self):
        self.breaks("fail-fast", "fail-fast: ${{ github.event_name == 'pull_request' }}", "fail-fast: false")

    def test_the_node_matrix(self):
        self.breaks("matrix-node=26", "node: [26]", "node: [24, 26]")
        self.assertEqual(run(read(SINGLE), "matrix-node=26")[0], 0)

    def test_a_matrix_outside_the_test_job(self):
        self.breaks("matrix-only-test", "  lint:\n    name: Lint\n    needs: changes\n",
                    "  lint:\n    name: Lint\n    strategy:\n      matrix:\n        os: [a]\n    needs: changes\n")

    def test_the_matrix_name_holds_every_key(self):
        self.breaks("matrix-name", "name: Test (node ${{ matrix.node }})", "name: Test")
        text = read(SINGLE).replace("        node: [26]\n", "        node: [26]\n        os: [ubuntu-24.04]\n")
        self.assertTrue(failed(text, "matrix-name"))

    def test_a_shard(self):
        self.breaks("no-shards", "        node: [26]\n", "        node: [26]\n        shard: [1, 2]\n")

    def test_the_install_command(self):
        self.breaks("install=npm ci", "run: npm ci", "run: npm install", count=1)

    def test_the_audit_job(self):
        self.breaks("audit-job", "--audit-level=high", "--audit-level=low")
        self.breaks("audit-job", "needs.changes.outputs.lockfile == 'true'", "true")
        self.breaks("audit-job", "      - name: Run unit tests\n        run: npm run test\n",
                    "      - name: Run unit tests\n        run: npm audit\n")

    def test_a_privileged_trigger(self):
        self.breaks("no-privileged-trigger", "  pull_request:\n", "  pull_request_target:\n")

    def test_needs_between_independent_jobs(self):
        self.breaks("no-needs-between", "  test:\n    name: Test (node ${{ matrix.node }})\n    needs: changes\n",
                    "  test:\n    name: Test (node ${{ matrix.node }})\n    needs: [changes, lint]\n")

    def test_a_job_name_that_lists_tasks(self):
        self.breaks("job-names", "name: Lint\n", "name: Lint, typecheck\n")

    def test_a_matrix_name_with_a_comma_between_matrix_values_is_not_a_task_list(self):
        for name in ("Test (${{ matrix.os }}, node ${{ matrix.node }})",
                     "Test (node ${{ matrix.node }}, shard ${{ matrix.shard }}/4)"):
            text = read(SINGLE).replace("name: Test (node ${{ matrix.node }})", f"name: {name}")
            self.assertEqual(run(text, "job-names")[0], 0, name)
        listing = read(SINGLE).replace("name: Test (node ${{ matrix.node }})",
                                       "name: Test (${{ matrix.node }}), lint")
        self.assertTrue(failed(listing, "job-names"))

    def test_the_checkout_depth(self):
        self.breaks("checkout-depth=default", "          persist-credentials: false\n",
                    "          fetch-depth: 0\n          persist-credentials: false\n")

    def test_the_text_assertions(self):
        self.assertTrue(failed(read(SINGLE), "text=nothing like this"))
        self.assertTrue(failed(read(SINGLE), "no-text=npm ci"))
        self.assertEqual(run(read(SINGLE), "text=npm ci", "no-text=yarn")[0], 0)

    def test_workers_needs_a_playwright_run_with_one_worker(self):
        self.assertTrue(failed(read(SINGLE), "workers=1"))
        plain = "jobs:\n  test:\n    steps:\n      - name: Run e2e tests\n        run: npx playwright test\n"
        self.assertTrue(failed(plain, "workers=1"))
        self.assertEqual(run(plain.replace("test\n", "test --workers=1\n"), "workers=1")[0], 0)

    def test_the_node_matrix_is_compared_as_a_set_of_majors(self):
        text = read(SINGLE).replace("        node: [26]\n", "        node: [26, 24, 22]\n")
        self.assertEqual(run(text, "matrix-node=22,24,26")[0], 0)
        self.assertEqual(run(text, "matrix-node=26,24,22")[0], 0)
        self.assertTrue(failed(text, "matrix-node=22,24"))
        self.assertTrue(failed(text, "matrix-node=22,24,26,28"))

    def test_a_timeout_argument_without_a_job_and_minutes_is_a_usage_error(self):
        for bad in ("timeout=lint", "timeout=lint:", "timeout=:10", "timeout=lint:ten"):
            self.assertEqual(run(read(SINGLE), bad)[0], 2, bad)
        self.assertEqual(run(read(SINGLE), "timeout=lint:10")[0], 0)

    def test_a_dependabot_entry_ends_at_the_next_top_level_key(self):
        text = ('version: 2\nupdates:\n  - package-ecosystem: "github-actions"\n    directory: "/"\n'
                '    schedule:\n      interval: "daily"\nregistries:\n  example:\n    schedule:\n'
                '      interval: "weekly"\n')
        self.assertTrue(failed(text, "dependabot"))
        flush = ('updates:\n- package-ecosystem: "github-actions"\n  directory: "/"\n  schedule:\n'
                 '    interval: "weekly"\nregistries:\n  x: y\n')
        self.assertEqual(run(flush, "dependabot")[0], 0)

    def test_the_security_audit_schedule_may_use_any_indent(self):
        text = AUDIT_WORKFLOW.replace("on:\n  schedule:\n    - cron: '17 6 * * 1'\n  workflow_dispatch:\n",
                                      "on:\n    schedule:\n      - cron: '17 6 * * 1'\n    workflow_dispatch:\n")
        self.assertNotEqual(text, AUDIT_WORKFLOW)
        self.assertEqual(run(text, "security-audit")[0], 0)
        self.assertTrue(failed(text.replace("17 6", "18 6"), "security-audit"))

    def test_a_comment_at_column_0_does_not_cut_a_block(self):
        text = read(SINGLE)
        for old in ("  lint:\n", "  contents: read\njobs:\n", "  push:\n"):
            commented = text.replace(old, "# a comment at column 0\n" + old, 1)
            self.assertNotEqual(commented, text, old)
            code, lines, _ = run(commented, *COMMON, *SINGLE_ONLY)
            self.assertEqual((code, lines), (0, ["PASS"]), old)

    def test_the_dependabot_messages_read_well(self):
        lines = failed(DEPENDABOT.replace('directory: "/"', 'directory: "/app"'), "dependabot")
        self.assertEqual(lines, ["FAIL dependabot: the github-actions entry has no directory /"])

    def test_workers_must_be_exactly_one(self):
        base = "jobs:\n  test:\n    steps:\n      - name: Run e2e tests\n        run: npx playwright test {flag}\n"
        for flag in ("--workers=10", "--workers=12", "--workers 2", "--workers=1x"):
            self.assertTrue(failed(base.format(flag=flag), "workers=1"), flag)
        for flag in ("--workers=1", "--workers=1 --reporter=line"):
            self.assertEqual(run(base.format(flag=flag), "workers=1")[0], 0, flag)

    def test_the_install_assertion_ignores_a_yarn_script_run(self):
        yarn = ("jobs:\n  lint:\n    steps:\n      - name: Install dependencies\n"
                "        run: yarn install --immutable\n      - name: Run lint\n        run: yarn run lint\n"
                "      - name: Run build\n        run: yarn build\n")
        self.assertEqual(run(yarn, "install=yarn install --immutable")[0], 0)
        self.assertTrue(failed(yarn.replace("yarn install --immutable", "yarn install"),
                               "install=yarn install --immutable"))
        self.assertTrue(failed(yarn.replace("yarn install --immutable", "yarn --frozen-lockfile"),
                               "install=yarn install --immutable"))

    def test_the_monorepo_affected_run(self):
        self.breaks("affected-run=turbo", "run: npx turbo run lint --affected", "run: npx turbo run lint",
                    path=MONO)
        self.breaks("affected-run=turbo", "run: npx turbo run lint\n", "run: npx turbo run lint --affected\n",
                    path=MONO)
        self.breaks("affected-run=turbo", "          fetch-depth: 0\n", "", path=MONO, count=1)

    def test_the_nx_and_pnpm_forms(self):
        nx = read(MONO).replace("npx turbo run lint --affected", "npx nx affected -t lint") \
                       .replace("run: npx turbo run lint\n", "run: npx nx run-many -t lint\n")
        self.assertTrue(failed(nx, "affected-run=turbo"))
        flt = read(MONO).replace("npx turbo run lint --affected", 'pnpm --filter "...[origin/main]" run lint') \
                        .replace("run: npx turbo run lint\n", "run: pnpm -r run lint\n")
        self.assertEqual(run(flt, "affected-run=pnpm")[0], 1)  # the other jobs still use turbo
        only_lint = (
            "jobs:\n  lint:\n    steps:\n"
            "      - name: Set up the Nx base\n        uses: nrwl/nx-set-shas@" + "0" * 40 + " # v4.0.0\n"
            "      - name: Check out the repo\n        uses: actions/checkout@" + "0" * 40 + " # v1.0.0\n"
            "        with:\n          fetch-depth: 0\n"
            "      - name: Lint affected packages\n        if: github.event_name == 'pull_request'\n"
            '        run: pnpm --filter "...[origin/main]" run lint\n'
            "      - name: Lint all packages\n        if: github.event_name == 'push'\n"
            "        run: pnpm -r run lint\n")
        self.assertEqual(run(only_lint, "affected-run=pnpm")[0], 0)
        nx_only = only_lint.replace('pnpm --filter "...[origin/main]" run lint', "nx affected -t lint") \
                           .replace("pnpm -r run lint", "nx run-many -t lint")
        self.assertEqual(run(nx_only, "affected-run=nx")[0], 0)
        self.assertTrue(failed(nx_only.replace("nrwl/nx-set-shas", "other/action"), "affected-run=nx"))



class OsLegs(unittest.TestCase):
    def test_a_floating_label_in_the_os_matrix_fails_pinned_runners(self):
        text = read(SINGLE).replace("        node: [26]\n", "        node: [26]\n        os: [ubuntu-24.04, macos-latest]\n")
        self.assertTrue(failed(text, "pinned-runners"))
        self.assertEqual(run(text.replace("macos-latest", "macos-15"), "pinned-runners")[0], 0)

    def test_the_matrix_name_must_hold_the_os_key(self):
        text = read(SINGLE).replace("        node: [26]\n", "        node: [26]\n        os: [ubuntu-24.04, macos-15]\n")
        self.assertTrue(failed(text, "matrix-name"))
        named = text.replace("name: Test (node ${{ matrix.node }})",
                             "name: Test (${{ matrix.os }}, node ${{ matrix.node }})")
        self.assertEqual(run(named, "matrix-name")[0], 0)


DEPENDABOT = 'version: 2\nupdates:\n  - package-ecosystem: "github-actions"\n    directory: "/"\n' \
             '    schedule:\n      interval: "weekly"\n'
AUDIT_WORKFLOW = (
    "name: Security audit\non:\n  schedule:\n    - cron: '17 6 * * 1'\n  workflow_dispatch:\n"
    "permissions:\n  contents: read\njobs:\n  audit:\n    name: Audit\n    runs-on: ubuntu-24.04\n"
    "    timeout-minutes: 10\n    steps:\n      - name: Check out the repo\n"
    "        uses: actions/checkout@" + "0" * 40 + " # v7.0.1\n        with:\n          persist-credentials: false\n"
    "      - name: Audit dependencies\n        run: npm audit --audit-level=high\n"
)


class SupportFiles(unittest.TestCase):
    def test_the_dependabot_assertion(self):
        self.assertEqual(run(DEPENDABOT, "dependabot")[0], 0)
        self.assertEqual(run(DEPENDABOT.replace('"github-actions"', "github-actions"), "dependabot")[0], 0)
        for old, new in (("github-actions", "npm"), ('directory: "/"', 'directory: "/app"'),
                         ('interval: "weekly"', 'interval: "daily"')):
            self.assertTrue(failed(DEPENDABOT.replace(old, new), "dependabot"), old)

    def test_the_three_dependabot_checks_must_hold_on_one_github_actions_entry(self):
        npm = ('  - package-ecosystem: "npm"\n    directory: "/"\n    schedule:\n      interval: "weekly"\n')
        wrong = ('  - package-ecosystem: "github-actions"\n    directory: "/.github"\n    schedule:\n'
                 '      interval: "monthly"\n')
        right = DEPENDABOT.split("updates:\n")[1]
        self.assertTrue(failed("version: 2\nupdates:\n" + npm + wrong, "dependabot"))
        self.assertEqual(run("version: 2\nupdates:\n" + wrong + right, "dependabot")[0], 0)
        self.assertEqual(run("version: 2\nupdates:\n" + npm + right, "dependabot")[0], 0)
        keys_first = ('  - directory: "/"\n    schedule:\n      interval: "weekly"\n'
                      '    package-ecosystem: "github-actions"\n')
        self.assertEqual(run("version: 2\nupdates:\n" + keys_first, "dependabot")[0], 0)
        with_list = right + "    ignore:\n      - dependency-name: \"x\"\n"
        self.assertEqual(run("version: 2\nupdates:\n" + with_list, "dependabot")[0], 0)

    def test_the_security_audit_assertion_reads_code_and_not_comments(self):
        comment = AUDIT_WORKFLOW.replace("run: npm audit --audit-level=high", "run: npm audit # --audit-level=high")
        self.assertTrue(failed(comment, "security-audit"))
        echo = AUDIT_WORKFLOW.replace("run: npm audit --audit-level=high", "run: echo --audit-level=high")
        self.assertTrue(failed(echo, "security-audit"))
        no_jobs = ("name: Security audit\non:\n  schedule:\n    - cron: '17 6 * * 1'\npermissions:\n"
                   "  contents: read\n# --audit-level=high\n")
        self.assertTrue(failed(no_jobs, "security-audit"))
        commented_cron = AUDIT_WORKFLOW.replace("on:\n  schedule:\n    - cron: '17 6 * * 1'\n  workflow_dispatch:\n",
                                                "on:\n  push:\n  # schedule:\n  #   - cron: '17 6 * * 1'\n")
        self.assertNotEqual(commented_cron, AUDIT_WORKFLOW)
        self.assertTrue(failed(commented_cron, "security-audit"))
        self.assertEqual(run(AUDIT_WORKFLOW.replace("npm audit", "pnpm audit"), "security-audit")[0], 0)

    def test_the_security_audit_assertion(self):
        self.assertEqual(run(AUDIT_WORKFLOW, "security-audit")[0], 0)
        for old, new in (("name: Security audit", "name: Audit"), ("17 6", "18 6"), ("contents: read", "contents: write"),
                         ("--audit-level=high", "--audit-level=low"), ("    timeout-minutes: 10\n", ""),
                         ("0" * 40 + " # v7.0.1", "v7"), ("          persist-credentials: false\n", ""),
                         ("  schedule:\n    - cron: '17 6 * * 1'\n", "")):
            self.assertTrue(failed(AUDIT_WORKFLOW.replace(old, new), "security-audit"), old)


class CommandLine(unittest.TestCase):
    def test_exit_codes_and_the_fail_line_format(self):
        code, lines, _ = run("name: X\n", "name=CI")
        self.assertEqual(code, 1)
        self.assertEqual(lines[-1], "FAIL")
        self.assertRegex(lines[0], r"^FAIL name: .+")

    def test_every_failed_assertion_has_one_line(self):
        code, lines, _ = run("name: X\n", "name=CI", "job=lint", "no-shards")
        self.assertEqual(code, 1)
        self.assertEqual([line.split(":")[0] for line in lines[:-1]], ["FAIL name", "FAIL job"])

    def test_an_unknown_assertion_exits_2(self):
        code, lines, err = run("name: CI\n", "no-such-assertion")
        self.assertEqual((code, lines), (2, []))
        self.assertIn("no-such-assertion", err)

    def test_an_unreadable_file_and_a_missing_argument_exit_2(self):
        for args in ([os.path.join(SKILL, "missing.yml"), "--assert", "name=CI"], ["-", "--assert", "job"]):
            done = subprocess.run([sys.executable, "-I", SCRIPT, *args], input="", capture_output=True, text=True)
            self.assertEqual(done.returncode, 2, args)
            self.assertEqual(done.stdout, "")

    def test_a_path_argument_reads_the_file(self):
        done = subprocess.run([sys.executable, "-I", SCRIPT, SINGLE, "--assert", "name=CI"],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (0, "PASS\n"))


class CoverageTable(unittest.TestCase):
    def test_the_table_and_the_not_claimed_ids_are_exactly_the_rule_ids(self):
        claimed = {rule_id for ids in COVERAGE for rule_id in ids}
        self.assertEqual(claimed | NOT_CLAIMED, {rule_id for _, rule_id, _ in all_rules()})
        self.assertFalse(claimed & NOT_CLAIMED)

    def test_every_assertion_of_the_table_is_known_to_the_script(self):
        args = {"name": "CI", "job": "lint", "install": "npm ci", "checkout-depth": "default",
                "affected-run": "turbo", "workers": "1", "no-text": "x", "matrix-node": "26",
                "timeout": "lint:10"}
        for name in COVERAGE.values():
            code, _, err = run(read(SINGLE), f"{name}={args[name]}" if name in args else name)
            self.assertIn(code, (0, 1), (name, err))


if __name__ == "__main__":
    unittest.main()
