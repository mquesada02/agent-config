"""Tests of create.md and of the templates (the Markdown structure and the fill table), through check_workflow.py."""
import os
import re
import subprocess
import sys
import unittest

from skill_files import SKILL, read

SCRIPT = os.path.join(SKILL, "scripts", "check_workflow.py")
CREATE = os.path.join(SKILL, "create.md")
SINGLE = os.path.join(SKILL, "templates", "single-package.yml")
MONO = os.path.join(SKILL, "templates", "monorepo.yml")
OWNERS = {"actions", "pnpm", "dorny", "nrwl"}
# The assertions of the npm app case that hold for a filled single-package template.
COMMON = [
    "name=CI", "job=changes,lint,typecheck,test,build,audit,ci-passed", "triggers", "concurrency", "permissions",
    "pinned-uses", "persist-credentials", "pinned-runners", "no-run-expr", "named-run-steps", "short-run-blocks",
    "short-comments", "timeouts", "timeout=changes:5", "timeout=ci-passed:5", "timeout=lint:10",
    "timeout=typecheck:10", "timeout=build:10", "timeout=audit:10", "timeout=test:15", "gate", "changes", "fail-fast",
    "matrix-only-test", "matrix-name", "no-shards", "audit-job", "no-privileged-trigger", "no-needs-between",
    "job-names", "no-text=secrets: inherit", "no-text=node_modules",
]


def check(text, *asserts):
    done = subprocess.run([sys.executable, "-I", SCRIPT, "-", "--assert", *asserts], input=text,
                          capture_output=True, text=True)
    return done.returncode, done.stdout.splitlines()


def section(text, heading):
    """The text under a heading line, up to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n") + len(heading) + 1
    match = re.search(rf"^#{{1,{level}}} ", text[start:], re.M)
    return text[start:start + match.start()] if match else text[start:]


def fenced_blocks(text):
    return re.findall(r"^```yaml\n(.*?)^```", text, re.S | re.M)


def pnpm_setup_step():
    """The pnpm setup step block of create.md."""
    (block,) = fenced_blocks(section(read(CREATE), "## Fill table").split("### Node versions")[0])
    return block


def fill_pnpm(path):
    """A template filled for pnpm, by text replacement of the fill table values."""
    text = read(path)
    text = text.replace("      - name: Set up Node\n", pnpm_setup_step() + "      - name: Set up Node\n")
    text = text.replace("cache: npm", "cache: pnpm").replace("run: npm ci", "run: pnpm install --frozen-lockfile")
    text = text.replace("run: npm run ", "run: pnpm run ").replace("run: npm audit", "run: pnpm audit")
    text = text.replace("run: npx turbo run", "run: pnpm exec turbo run")
    return text.replace("'package-lock.json'", "'pnpm-lock.yaml'")


def single_pnpm():
    return fill_pnpm(SINGLE)


class CreateSteps(unittest.TestCase):
    def setUp(self):
        self.text = read(CREATE)
        self.steps = re.findall(r"^(\d+)\. (.*)$", section(self.text, "## Steps"), re.M)

    def test_there_are_seven_numbered_steps_in_order(self):
        self.assertEqual([number for number, _ in self.steps], [str(i) for i in range(1, 8)])
        first_words = ["Run the intake", "Pick the template", "Fill the template", "Load and apply",
                       "Write the files", "Run actionlint", "Self-review"]
        for (_, line), word in zip(self.steps, first_words):
            self.assertTrue(line.startswith(word), (word, line))

    def test_the_intake_is_the_only_input_besides_the_two_support_files(self):
        self.assertIn("Read only the intake JSON", self.text)
        self.assertIn("The one exception is step 5", self.text)
        self.assertIn("the Dependabot file and `security-audit.yml`", self.text)

    def test_an_existing_ci_workflow_and_a_null_lockfile_write_nothing(self):
        step = section(self.text, "## Steps").split("\n2. ")[0]
        for needle in (".github/workflows/ci.yml", ".github/workflows/ci.yaml", "lockfile: null", "COST-05",
                       "write nothing"):
            self.assertIn(needle, step)
        self.assertEqual(step.count("write nothing"), 2)

    def test_a_null_lockfile_names_the_rule_id_in_the_sentence(self):
        step = section(self.text, "## Steps").split("\n2. ")[0]
        self.assertIn("name the rule id `COST-05` in that sentence", step)

    def test_the_final_message_shows_each_written_file_whole_and_nothing_after_the_approval_line(self):
        step = section(self.text, "## Steps").split("\n7. ")[1]
        self.assertIn("the whole file, line by line", step)
        self.assertIn("never a summary", step)
        self.assertIn("Write no text after the approval line", step)
        self.assertIn("in `## Created`", step)

    def test_a_dependabot_file_with_no_entry_gets_only_the_entry(self):
        step = section(self.text, "## Steps").split("\n5. ")[1].split("\n6. ")[0]
        self.assertIn("has no `github-actions` entry, add only that entry", step)
        self.assertIn(".github/dependabot.yaml", step)
        self.assertIn("leave it unchanged", step)

    def test_an_existing_security_audit_file_is_left_unchanged(self):
        step = section(self.text, "## Steps").split("\n5. ")[1].split("\n6. ")[0]
        self.assertIn(".github/workflows/security-audit.yaml", step)
        self.assertIn("leave that file unchanged", step)

    def test_a_removed_job_and_a_missing_test_runner_are_reported(self):
        steps = section(self.text, "## Steps")
        self.assertIn("name the removed job and the reason in the `## Created` section", steps)
        self.assertIn("A line for each removed job, and for a missing test runner", steps)
        self.assertIn("Without a runner, the `test` job is removed", self.text)

    def test_actionlint_runs_in_the_json_form_up_to_three_times_and_never_installs(self):
        step = section(self.text, "## Steps").split("\n6. ")[1].split("\n7. ")[0]
        self.assertIn("`actionlint -format '{{json .}}'`", step)
        self.assertIn("up to 3 runs in all", step)
        self.assertIn("as its own call, never chained with another command", step)
        self.assertIn("Never install a tool", step)

    def test_the_self_review_sets_the_message_order(self):
        step = section(self.text, "## Steps").split("\n7. ")[1]
        for needle in ("`## Created`", "`### <path>`", "fenced `yaml` block",
                       "`# ci-pipelines review: .github/workflows/ci.yml (created)`", "`**Result:`"):
            self.assertIn(needle, step)
        self.assertLess(step.index("`## Created`"), step.index("`### <path>`"))
        self.assertLess(step.index("`### <path>`"), step.index("`# ci-pipelines review"))

    def test_both_templates_use_npm_as_the_default_manager(self):
        for path in (SINGLE, MONO):
            text = read(path)
            self.assertNotIn("pnpm", text, path)
            self.assertIn("run: npm ci", text, path)
            self.assertIn("cache: npm", text, path)

    def test_the_monorepo_table_uses_the_run_a_tool_cell_and_a_workspaces_step_for_each_manager(self):
        table = section(self.text, "### Monorepo tools")
        turbo = next(line for line in table.splitlines() if line.startswith("| `turbo`"))
        nx = next(line for line in table.splitlines() if line.startswith("| `nx`"))
        for row in (turbo, nx):
            self.assertIn("<run a tool>", row)
            self.assertNotIn("pnpm turbo", row)
            self.assertNotIn("<package manager> nx", row)
        workspaces = next(line for line in table.splitlines() if line.startswith("| `workspaces`"))
        for step in ("npm run <task> --workspaces --if-present", "yarn workspaces foreach --all run <task>",
                     "pnpm -r run <task>"):
            self.assertIn(step, workspaces)
        self.assertIn("`npx` for npm", table)

    def test_the_script_names_are_exact(self):
        self.assertIn("exactly `lint`, `typecheck`, `test` and `build`", self.text)
        self.assertIn("`test:unit`", self.text)


class SupportBlocks(unittest.TestCase):
    def setUp(self):
        self.text = read(CREATE)

    def block(self, heading):
        blocks = fenced_blocks(section(self.text, heading))
        self.assertEqual(len(blocks), 1, heading)
        return blocks[0]

    def test_the_dependabot_block_passes_the_dependabot_assertion(self):
        block = self.block("### Dependabot block")
        self.assertIn('package-ecosystem: "github-actions"', block)
        self.assertEqual(check(block, "dependabot"), (0, ["PASS"]))

    def test_the_security_audit_block_passes_the_security_audit_assertion(self):
        block = self.block("### Security audit block")
        self.assertEqual(check(block, "security-audit", "pinned-uses", "persist-credentials", "pinned-runners",
                               "no-run-expr", "named-run-steps", "permissions", "no-privileged-trigger",
                               "timeouts", "no-text=node_modules"), (0, ["PASS"]))

    def test_the_playwright_steps_pass_workers_when_added_to_the_test_job(self):
        block = self.block("### Playwright steps")
        text = read(SINGLE).replace("        run: npm run test\n", "        run: npm run test\n" + block)
        self.assertEqual(check(text, *COMMON, "workers=1", "no-text=actions/cache"), (0, ["PASS"]))
        self.assertIn("--workers=1", block)

    def test_no_block_and_no_template_holds_a_fill_comment(self):
        blocks = fenced_blocks(self.text) + [read(SINGLE), read(MONO)]
        for block in blocks:
            self.assertNotIn("fill", block.lower())
            self.assertNotRegex(block, r"(?m)^\s*#\s*(TODO|CHANGE|REPLACE)")


class Owners(unittest.TestCase):
    def test_the_owners_in_uses_are_only_the_allowed_ones(self):
        for text in (read(SINGLE), read(MONO), read(CREATE)):
            owners = set(re.findall(r"uses:\s*([\w.-]+)/[\w.-]+@", text))
            self.assertLessEqual(owners, OWNERS)
        # the templates and the support blocks use actions, pnpm and dorny; nrwl comes from the Nx fill row
        used = set(re.findall(r"uses:\s*([\w.-]+)/", read(SINGLE) + read(MONO) + read(CREATE)))
        self.assertEqual(used, {"actions", "pnpm", "dorny"})
        self.assertIn("nrwl/nx-set-shas", read(CREATE))


class FillByReplacement(unittest.TestCase):
    """The fill table changes values only: the filled templates must still pass the assertions."""

    def test_the_single_package_template_filled_for_pnpm_passes(self):
        text = single_pnpm()
        self.assertEqual(check(text, *COMMON, "matrix-node=26", "install=pnpm install --frozen-lockfile",
                               "checkout-depth=default", "text=pnpm audit --audit-level=high"), (0, ["PASS"]))
        self.assertNotIn("npm ci", text)

    def test_a_filled_matrix_of_three_majors_passes_matrix_node(self):
        text = read(SINGLE).replace("        node: [26]\n", "        node: [22, 24, 26]\n")
        self.assertEqual(check(text, *COMMON, "matrix-node=22,24,26"), (0, ["PASS"]))

    def test_the_os_legs_row_passes_the_matrix_name_and_the_runner_assertions(self):
        text = read(SINGLE).replace("        node: [26]\n",
                                    "        node: [26]\n        os: [ubuntu-24.04, macos-15, windows-2025]\n")
        text = text.replace("name: Test (node ${{ matrix.node }})",
                            "name: Test (${{ matrix.os }}, node ${{ matrix.node }})")
        head, _, tail = text.partition("  test:\n")
        test_job, sep, rest = tail.partition("\n  build:\n")
        test_job = test_job.replace("runs-on: ubuntu-24.04", "runs-on: ${{ matrix.os }}")
        text = head + "  test:\n" + test_job + sep + rest
        self.assertEqual(check(text, *COMMON, "matrix-node=26"), (0, ["PASS"]))
        self.assertEqual(check(text.replace("macos-15", "macos-latest"), "pinned-runners")[0], 1)

    def test_a_removed_job_must_leave_the_gate(self):
        text = read(SINGLE)
        job = text[text.index("  typecheck:\n"):text.index("  test:\n")]
        removed = text.replace(job, "")
        self.assertEqual(check(removed, "gate")[0], 0)
        self.assertEqual(check(read(SINGLE).replace("needs: [changes, lint, typecheck, test, build, audit]",
                                                    "needs: [changes, lint, test, build, audit]"), "gate")[0], 1)
        self.assertEqual(check(removed, "no-job=typecheck")[0], 0)


if __name__ == "__main__":
    unittest.main()
