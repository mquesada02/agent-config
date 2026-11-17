"""Tests of create.md and of the templates (the Markdown structure and the fill table), through check_workflow.py."""
import os
import re
import subprocess
import sys
import unittest

from skill_files import SKILL, cd_form, ci_only_form, read

SCRIPT = os.path.join(SKILL, "scripts", "check_workflow.py")
CREATE = os.path.join(SKILL, "create.md")
SINGLE = os.path.join(SKILL, "templates", "single-package.yml")
MONO = os.path.join(SKILL, "templates", "monorepo.yml")
OWNERS = {"actions", "pnpm", "dorny", "nrwl", "hashicorp"}
DEPLOY = os.path.join(SKILL, "templates", "deploy.yml")
ROLLBACK = os.path.join(SKILL, "templates", "rollback.yml")
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
        # the lockfile stop, the CI-only stop and the existing-CD-file rule
        self.assertEqual(step.count("write nothing"), 3)

    def test_a_null_lockfile_names_the_rule_id_in_the_sentence(self):
        step = section(self.text, "## Steps").split("\n2. ")[0]
        self.assertIn("name the rule id `COST-05` in that sentence", step)

    def test_the_final_message_shows_each_written_file_whole_and_nothing_after_the_approval_line(self):
        step = section(self.text, "## Steps").split("\n7. ")[1]
        self.assertIn("the whole file, line by line", step)
        self.assertIn("never a summary", step)
        self.assertIn("Write no text after the approval line", step)
        self.assertIn("say so in `## Created`", step)

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
                       "`# cicd-pipelines review: .github/workflows/ci.yml (created)`", "`**Result:`"):
            self.assertIn(needle, step)
        self.assertLess(step.index("`## Created`"), step.index("`### <path>`"))
        self.assertLess(step.index("`### <path>`"), step.index("`# cicd-pipelines review"))

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
        # the templates and the support blocks use actions, pnpm and dorny; nrwl comes from the Nx fill row and
        # hashicorp from the Terraform steps
        used = set(re.findall(r"uses:\s*([\w.-]+)/", read(SINGLE) + read(MONO) + read(CREATE)))
        self.assertEqual(used, {"actions", "pnpm", "dorny", "hashicorp"})
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


CD_FILE_ASSERTS = ["pinned-uses", "permissions", "no-run-expr", "named-run-steps", "pinned-runners", "timeouts",
                   "persist-credentials", "no-privileged-trigger"]
DEPLOY_ASSERTS = ["stage-environments", "concurrency-cd", "no-install-in-deploy", "digest-check", "package-upload"]


def terraform_block():
    (block,) = fenced_blocks(section(read(CREATE), "### Terraform steps"))
    return block


def terraform_fill(text):
    """A CD template filled for the Terraform target, by the 4 changes of the "Terraform steps" section."""
    text = text.replace("DEPLOY_TARGET: lambda", "DEPLOY_TARGET: terraform")
    block = terraform_block()
    text = re.sub(r"(      - name: Deploy the [^\n]*\n)", lambda match: block + match.group(1), text)
    text = text.replace("      - name: Check out the deploy script\n", "      - name: Check out the repo\n")
    text = text.replace("          sparse-checkout: scripts\n", "")
    return text.replace("vars.LAMBDA_FUNCTION", "vars.DEPLOY_NAME")


def step1():
    return section(read(CREATE), "## Steps").split("\n2. ")[0]


def numbered_step(number):
    steps = section(read(CREATE), "## Steps")
    return re.split(r"\n\d\. ", "\n" + steps)[number]


class CdQuestions(unittest.TestCase):
    def setUp(self):
        self.text = section(read(CREATE), "## Questions")

    def test_it_asks_ci_cd_or_both_and_the_deploy_target_and_nothing_else(self):
        self.assertIn('ask "CI, CD or both?"', self.text)
        self.assertIn("ask for the deploy target", self.text)
        self.assertIn("ask nothing else", self.text.lower())
        self.assertIn("A CI-only request asks no question", self.text)

    def test_the_deploy_target_order_is_the_request_then_the_facts_then_a_question(self):
        order = [self.text.index(needle) for needle in
                 ("the target that the request names", "else the one target that the facts show", "else ask")]
        self.assertEqual(order, sorted(order))

    def test_each_fact_value_has_a_place_in_the_mapping(self):
        for needle in ("`lambda` shows AWS Lambda", "`terraform` shows Terraform", "`s3`", "`cloudfront`", "`ecs`",
                       "`container-registry`", "`github-pages`", "`cloudflare`", "`vercel`", "`netlify`",
                       "The kind `aws` alone shows nothing", "`opentofu`", "`cdk`", "`pulumi`", "`serverless`",
                       "`sam`", "`cloudformation`", "With none, or with two or more, ask",
                       "A request that names two targets also gets the question",
                       "names both when they differ"):
            self.assertIn(needle, self.text)


class CdStepOne(unittest.TestCase):
    def setUp(self):
        self.step = step1()

    def test_a_null_lockfile_stops_every_request(self):
        self.assertIn("`lockfile: null`", self.step)
        self.assertIn("name the rule id `COST-05`", self.step)

    def test_a_ci_only_request_with_a_ci_file_writes_nothing_in_both_file_forms(self):
        self.assertIn("A CI-only request with a CI file: write nothing", self.step)
        self.assertIn("`.github/workflows/ci.yml` or `.github/workflows/ci.yaml`", self.step)
        self.assertIn("(`ci.yml` when both exist)", self.step)

    def test_a_ci_only_request_with_no_ci_file_goes_on_and_writes_the_ci_only_file(self):
        self.assertNotIn("A CI-only request: write nothing", self.step)
        self.assertIn("A CI-only request asks no question", read(CREATE))
        self.assertIn("Write `.github/workflows/ci.yml` only when no CI file exists", numbered_step(5))
        self.assertIn("In every other run that writes `ci.yml`, remove each block with its marker lines",
                      numbered_step(2))

    def test_the_ci_yaml_file_gives_the_call_path_row_of_deploy_yml(self):
        row = ("| CI file `.github/workflows/ci.yaml` (a CD request with a template and a CI file) | The `uses:` line "
               "of the `ci` job of `deploy.yml` is `./.github/workflows/ci.yaml`")
        self.assertIn(row, section(read(CREATE), "## Fill table"))
        self.assertIn("    uses: ./.github/workflows/ci.yml\n", read(DEPLOY))

    def test_a_target_with_no_template_writes_no_cd_file_and_both_goes_on_as_ci_only(self):
        self.assertIn("no template exists for the target", self.step)
        self.assertIn("S3 with a CDN, a signed S3 bundle and every other target", self.step)
        self.assertIn('For "both", go on as a CI-only request', self.step)
        self.assertIn("For CD alone, offer a review of the existing workflows, or say that there is nothing to review",
                      self.step)

    def test_no_build_script_stops_the_cd_files_and_names_deploy_01(self):
        self.assertIn("no package has a `build` script in the `scripts` fact", self.step)
        self.assertIn("a build script is needed first and name the rule id `DEPLOY-01`", self.step)
        self.assertIn("Say which cause holds", self.step)

    def test_an_existing_cd_file_is_never_written_in_either_form(self):
        self.assertIn("`.github/workflows/<name>.yml` or `.github/workflows/<name>.yaml`", self.step)
        self.assertIn("write nothing for that file (neither form) and offer a review of it", self.step)
        self.assertIn("Write each CD file that does not exist", self.step)

    def test_a_cd_request_with_no_ci_file_writes_ci_yml_with_the_cd_part_whichever_cd_files_exist(self):
        self.assertIn("no CI file (whichever CD files exist): also write `ci.yml` with the CD part", self.step)

    def test_a_cd_request_with_a_ci_file_gives_rows_and_edits_nothing(self):
        for needle in ("(even for \"both\")", "write no `ci.yml`, no Dependabot file and no `security-audit.yml`",
                       "the final message holds report rows and no file is edited", "COST-01 (CD part)",
                       "`workflow_call` trigger with no `code` output", "One row names the rule GRAPH-06",
                       "the severity of its rule", "When the CI file lacks the CD part",
                       "The fix-on-approval flow edits the CI file after the owner approves"):
            self.assertIn(needle, self.step)

    def test_the_rules_are_in_the_spec_order(self):
        needles = ["`lockfile: null`", "A CI-only request with a CI file", "no CD file can be written",
                   "A CD request with a template: for each", "no CI file (whichever CD files exist)",
                   "a CI file (even for"]
        positions = [self.step.index(needle) for needle in needles]
        self.assertEqual(positions, sorted(positions))


class CdLaterSteps(unittest.TestCase):
    def test_step_two_picks_the_cd_templates_and_decides_the_cd_part_blocks(self):
        step = numbered_step(2)
        for needle in ("templates/deploy.yml", "templates/release.yml", "templates/rollback.yml", "templates/scripts/",
                       "`# cd-part:start`", "`# cd-part:end`", "remove the `push:` trigger",
                       "only when step 1 gives a CD request with a template and no CI file",
                       "remove each block with its marker lines"):
            self.assertIn(needle, step)

    def test_step_three_fills_release_yml_and_keeps_the_job_graph(self):
        step = numbered_step(3)
        self.assertIn("the package manager row also fills `release.yml`", step)
        self.assertIn("the job graph", step)
        self.assertIn("the Terraform steps are the only change of steps", step)

    def test_step_four_loads_the_cd_rule_files_and_publish_only_for_a_published_package(self):
        step = numbered_step(4)
        for needle in ("rules/deploy.md", "rules/rollback.md", "rules/release.md",
                       "rules/publish.md](rules/publish.md) only when the `package_kind` fact finds a published package",
                       "30 for a deploy job, 10 for `package`, 5 for `skip-notice`, 15 for the release job and 30 for the "
                       "rollback job"):
            self.assertIn(needle, step)

    def test_step_five_writes_scripts_only_with_a_deploy_or_rollback_file_and_makes_them_executable(self):
        step = numbered_step(5)
        for needle in ("only when no CI file exists", "scripts/deploy-and-verify.sh", "scripts/check-staged.sh",
                       "only in a run that writes `deploy.yml` or `rollback.yml`", "`chmod +x`", "as its own Bash call",
                       "print the exact `chmod` command", "Never overwrite an existing file or script",
                       "In a run that writes `ci.yml`, glob", "In a run that writes `ci.yml`, take the"):
            self.assertIn(needle, step)

    def test_step_six_and_seven_cover_the_cd_message(self):
        six, seven = numbered_step(6), numbered_step(7)
        self.assertIn("comes from the call of an existing CI file that lacks the CD part", six)
        for needle in ("a `bash` block for a shell script", "in the order `deploy.yml`, `release.yml`, `rollback.yml`",
                       "push to main (`Deploy`)", "the final tag (`Deploy`, prod)", "the dispatch (`Rollback`)",
                       "push to main (`Release`)", "raises no PROTECT row", "the Changesets config",
                       "the message offers a review for protection"):
            self.assertIn(needle, seven)

    def test_the_intro_names_cd_and_the_repo_scripts_as_a_second_exception(self):
        text = read(CREATE)
        self.assertIn("Step 5 also copies the two repo scripts", text)
        self.assertIn("which is a second exception", text)
        self.assertIn("Create mode never writes branch protection", text)


class TerraformFill(unittest.TestCase):
    def test_the_terraform_block_has_a_full_sha_pin_with_a_version_comment_and_no_other_owner(self):
        block = terraform_block()
        self.assertRegex(block, r"uses: hashicorp/setup-terraform@[0-9a-f]{40} # v\d+\.\d+\.\d+")
        self.assertIn("run: terraform init -input=false", block)

    def test_a_filled_deploy_yml_passes_the_cd_assertions_and_keeps_the_digest_check(self):
        text = terraform_fill(read(DEPLOY))
        self.assertEqual(check(text, *CD_FILE_ASSERTS, *DEPLOY_ASSERTS), (0, ["PASS"]))
        self.assertNotIn("LAMBDA_FUNCTION", text)
        self.assertNotIn("sparse-checkout", text)
        self.assertNotIn("DEPLOY_TARGET: lambda", text)

    def test_every_job_that_runs_the_deploy_script_gets_the_target_the_steps_and_the_name_variable(self):
        for path in (DEPLOY, ROLLBACK):
            text = terraform_fill(read(path))
            runs = text.count("deploy-and-verify.sh")
            self.assertGreaterEqual(runs, 1)
            self.assertEqual(text.count("DEPLOY_TARGET: terraform"), runs, path)
            self.assertEqual(text.count("hashicorp/setup-terraform@"), runs, path)
            self.assertEqual(text.count("terraform init -input=false"), runs, path)
            self.assertEqual(text.count("vars.DEPLOY_NAME"), runs, path)
            for job in re.split(r"(?m)^  (?=[a-z][\w-]*:\n)", text)[1:]:
                if "deploy-and-verify.sh" in job:
                    role = job.index("Assume the")
                    self.assertLess(role, job.index("Set up Terraform"))
                    self.assertLess(job.index("Initialize Terraform"), job.index("Deploy the"))

    def test_a_filled_rollback_yml_passes_the_rollback_assertions(self):
        text = terraform_fill(read(ROLLBACK))
        self.assertEqual(check(text, *CD_FILE_ASSERTS, "concurrency-cd", "no-install-in-deploy", "digest-check",
                               "rollback-workflow"), (0, ["PASS"]))

    def test_the_dev_and_staging_checkout_is_full_and_renamed(self):
        text = terraform_fill(read(DEPLOY))
        self.assertNotIn("Check out the deploy script", text)
        self.assertEqual(text.count("Check out the repo"), 2)

    def test_the_terraform_block_sits_after_the_playwright_section_so_the_pnpm_step_read_holds(self):
        text = read(CREATE)
        self.assertLess(text.index("### Playwright steps"), text.index("### Terraform steps"))
        self.assertLess(text.index("### Terraform steps"), text.index("## Support files"))
        self.assertLess(text.index("### Node versions"), text.index("### Terraform steps"))


class ReviewSentence(unittest.TestCase):
    def test_review_md_says_that_create_asks_the_cd_questions_and_the_intake_asks_only_the_runner_size_question(self):
        text = read(os.path.join(SKILL, "review.md"))
        self.assertNotIn("This is the only question that the intake asks.", text)
        self.assertIn("The intake asks only this runner-size question. Create mode asks the CD questions of "
                      "[create.md](create.md) (CI, CD or both, and the deploy target).", text)

    def test_the_router_says_that_create_covers_cd_and_asks_the_cd_questions(self):
        text = read(os.path.join(SKILL, "SKILL.md"))
        self.assertIn("new CI workflow, CD workflows or both", text)
        self.assertIn("It asks the CD questions when they are open", text)


class CdPartBlocks(unittest.TestCase):
    def test_each_ci_template_holds_the_two_marked_blocks(self):
        for path in (SINGLE, MONO):
            text = read(path)
            self.assertEqual(text.count("# cd-part:start"), 2, path)
            self.assertEqual(text.count("# cd-part:end"), 2, path)
            self.assertIn("  pull_request:\n  # cd-part:start\n  workflow_call:\n", text)
            self.assertIn("uses: actions/upload-artifact@", text)
            for word in ("fill", "shard"):
                for line in text.splitlines():
                    if "cd-part" in line:
                        self.assertNotIn(word, line.lower())

    def test_removing_the_blocks_gives_the_ci_only_file_and_it_passes_the_ci_assertions(self):
        for path in (SINGLE, MONO):
            text = ci_only_form(read(path))
            self.assertNotIn("cd-part", text)
            self.assertNotIn("workflow_call", text)
            self.assertNotIn("upload-artifact", text)
            self.assertIn("  push:\n    branches: [main]\n", text)
        self.assertEqual(check(ci_only_form(read(SINGLE)), *COMMON, "matrix-node=26", "install=npm ci",
                               "checkout-depth=default"), (0, ["PASS"]))

    def test_keeping_the_blocks_gives_the_cd_form_that_passes_triggers_cd(self):
        for path in (SINGLE, MONO):
            text = cd_form(read(path))
            self.assertNotIn("cd-part", text)
            self.assertNotIn("  push:\n", text)
            self.assertIn("  workflow_call:\n    outputs:\n      code:\n", text)
            self.assertIn("value: ${{ jobs.changes.outputs.code }}", text)
            self.assertIn("name: dist\n          path: dist\n          retention-days: 1", text)
            self.assertEqual(check(text, "triggers-cd", "pinned-uses", "gate", "timeouts"), (0, ["PASS"]), path)

    def test_the_raw_template_still_passes_the_ci_assertions(self):
        self.assertEqual(check(read(SINGLE), *COMMON, "matrix-node=26", "install=npm ci", "checkout-depth=default"),
                         (0, ["PASS"]))

    def test_the_cd_blocks_use_only_actions_owner_actions(self):
        for path in (SINGLE, MONO):
            text = read(path)
            blocks = re.findall(r"# cd-part:start\n(.*?)# cd-part:end", text, re.S)
            self.assertEqual(len(blocks), 2)
            for block in blocks:
                for owner in re.findall(r"uses:\s*([\w.-]+)/", block):
                    self.assertEqual(owner, "actions")


if __name__ == "__main__":
    unittest.main()
