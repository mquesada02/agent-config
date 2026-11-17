"""Text checks of the CD templates for the stories that no assertion of check_workflow.py covers."""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

from fake_cli import trash
from skill_files import SKILL, read

TEMPLATES = os.path.join(SKILL, "templates")
DEPLOY = read(os.path.join(TEMPLATES, "deploy.yml"))
RELEASE = read(os.path.join(TEMPLATES, "release.yml"))
ROLLBACK = read(os.path.join(TEMPLATES, "rollback.yml"))


def job(text, job_id):
    """The text of one job: from its key at two spaces of indent to the next job key."""
    found = re.search(r"(?ms)^  " + re.escape(job_id) + r":\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)", text)
    assert found, f"job {job_id} is missing"
    return found.group(0)


class DeployTemplate(unittest.TestCase):
    def test_the_package_job_assumes_the_artifacts_role_after_it_downloads_the_build(self):
        package = job(DEPLOY, "package")
        self.assertLess(package.index("actions/download-artifact@"),
                        package.index("aws-actions/configure-aws-credentials@"))
        self.assertIn("role-to-assume: ${{ vars.AWS_ROLE_ARTIFACTS }}", package)

    def test_the_skip_notice_runs_only_on_a_docs_only_push(self):
        self.assertIn("if: needs.ci.outputs.code != 'true'", job(DEPLOY, "skip-notice"))

    def test_dev_and_staging_run_only_when_the_push_changed_code_and_each_needs_the_earlier_stage(self):
        dev, staging = job(DEPLOY, "deploy-dev"), job(DEPLOY, "deploy-staging")
        for text in (dev, staging):
            self.assertIn("if: needs.ci.outputs.code == 'true'", text)
        self.assertIn("needs: [ci, package]", dev)
        self.assertIn("needs: [ci, deploy-dev]", staging)

    def test_prod_runs_only_for_a_tag_with_no_ci_condition_and_checks_main_and_the_staging_record(self):
        prod = job(DEPLOY, "deploy-prod")
        self.assertIn("if: github.ref_type == 'tag'", prod)
        self.assertNotIn("needs", prod)
        self.assertIn("fetch-depth: 0", prod)
        self.assertLess(prod.index("git merge-base --is-ancestor HEAD origin/main"),
                        prod.index('./scripts/check-staged.sh "$SHA"'))
        self.assertLess(prod.index('./scripts/check-staged.sh "$SHA"'),
                        prod.index("aws-actions/configure-aws-credentials@"))
        self.assertIn("deployments: read", prod)

    def test_the_final_tag_pattern_and_the_ci_call(self):
        self.assertIn("tags: ['v[0-9]+.[0-9]+.[0-9]+']", DEPLOY)
        self.assertIn("if: github.ref_type == 'branch'", job(DEPLOY, "ci"))
        self.assertIn("uses: ./.github/workflows/ci.yml", job(DEPLOY, "ci"))

    def test_the_workflow_has_top_level_read_permissions_and_no_workflow_level_concurrency(self):
        self.assertRegex(DEPLOY, r"(?m)^permissions:\n  contents: read\n")
        self.assertNotRegex(DEPLOY, r"(?m)^concurrency:")

    def test_every_deploy_job_sets_the_lambda_target_and_reads_its_settings_from_variables(self):
        for name in ("deploy-dev", "deploy-staging", "deploy-prod"):
            text = job(DEPLOY, name)
            self.assertIn("DEPLOY_TARGET: lambda", text)
            for setting in ("ARTIFACT_BUCKET", "LAMBDA_FUNCTION", "VERSION_URL"):
                self.assertIn("${{ vars." + setting + " }}", text)


class RollbackTemplate(unittest.TestCase):
    def test_the_rollback_has_one_job_that_shares_the_deploy_group_and_never_builds(self):
        text = job(ROLLBACK, "roll-back")
        self.assertIn("group: deploy-${{ inputs.environment }}", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertNotRegex(text, r"(?i)\b(install|build)\b")
        self.assertIn("options: [dev, staging, prod]", ROLLBACK)
        self.assertRegex(ROLLBACK, r"(?m)^permissions:\n  contents: read\n")


class ReleaseTemplate(unittest.TestCase):
    def test_the_release_has_only_the_push_to_main_and_dispatch_triggers(self):
        on = RELEASE[RELEASE.index("on:\n"):RELEASE.index("concurrency:")]
        self.assertEqual(re.findall(r"(?m)^  (\w+):", on), ["push", "workflow_dispatch"])
        self.assertIn("branches: [main]", on)

    def test_the_release_uses_changesets_the_app_token_a_frozen_install_and_no_cache(self):
        text = job(RELEASE, "release")
        self.assertIn("changesets/action@", text)
        self.assertIn("createGithubReleases: true", text)
        self.assertIn("environment: release", text)
        self.assertIn("actions/create-github-app-token@", text)
        self.assertIn("pnpm install --frozen-lockfile", text)
        self.assertIn("package-manager-cache: false", text)
        self.assertNotIn("cache:", text.replace("package-manager-cache:", ""))
        self.assertIn("node-version: 24", text)
        self.assertIn("id-token: write", text)
        self.assertIn("GITHUB_TOKEN: ${{ steps.app.outputs.token }}", text)
        self.assertNotIn("NPM_TOKEN", RELEASE)

    def test_the_release_has_one_workflow_group_with_no_cancel(self):
        self.assertRegex(RELEASE, r"(?m)^concurrency:\n  group: release\n  cancel-in-progress: false\n")
        self.assertRegex(RELEASE, r"(?m)^permissions:\n  contents: read\n")


class EveryCdFile(unittest.TestCase):
    FILES = sorted(glob.glob(os.path.join(TEMPLATES, "deploy.yml")) + glob.glob(os.path.join(TEMPLATES, "release.yml"))
                   + glob.glob(os.path.join(TEMPLATES, "rollback.yml")) + glob.glob(os.path.join(TEMPLATES, "scripts", "*")))

    def test_there_are_three_templates_and_two_scripts(self):
        self.assertEqual(sorted(os.path.basename(p) for p in self.FILES),
                         ["check-staged.sh", "deploy-and-verify.sh", "deploy.yml", "release.yml", "rollback.yml"])

    def test_no_file_holds_a_url_or_a_typed_role_arn_or_a_long_lived_key(self):
        for path in self.FILES:
            text = read(path)
            self.assertNotRegex(text, r"https?://", path)
            self.assertNotIn("arn:aws:iam::", text, path)
            self.assertNotRegex(text, r"aws-access-key-id|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY", path)

    def test_every_external_action_has_a_full_sha_and_a_version_comment(self):
        for path in self.FILES:
            for line in re.findall(r"uses:\s*(?!\./)(\S.*)", read(path)):
                self.assertRegex(line, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$", path)

    @unittest.skipUnless(shutil.which("actionlint"), "actionlint is not installed, so the templates are not linted")
    def test_actionlint_passes_on_the_cd_templates(self):
        # deploy.yml calls ./.github/workflows/ci.yml, so the run uses the ci.yml of the clean CD fixture as a stand-in.
        root = tempfile.mkdtemp(prefix="cd-lint-")
        self.addCleanup(trash, root)
        workflows = os.path.join(root, ".github", "workflows")
        os.makedirs(workflows)
        for name in ("deploy.yml", "release.yml", "rollback.yml"):
            shutil.copy(os.path.join(TEMPLATES, name), workflows)
        shutil.copy(os.path.join(SKILL, "evals", "clean-cd", "repo", ".github", "workflows", "ci.yml"), workflows)
        done = subprocess.run(["actionlint", "-format", "{{json .}}"], cwd=root, capture_output=True, text=True)
        errors = [e for e in json.loads(done.stdout or "[]") if not e["filepath"].endswith("ci.yml")]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
