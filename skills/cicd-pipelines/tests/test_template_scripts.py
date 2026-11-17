"""Dry-run tests of the CD template scripts, run with fake `aws`, `gh`, `curl` and `terraform` on PATH.

They prove the digest check, the version check and the staging-record check, and the success paths.
"""
import unittest

from fake_cli import SHA, Sandbox

DEPLOY = "deploy-and-verify.sh"
STAGED = "check-staged.sh"
ARGS = ("example-bucket", SHA, "example-function", "version-endpoint")


class DeployAndVerify(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def test_the_lambda_success_path_deploys_in_order_and_moves_the_alias(self):
        run = self.box.run(DEPLOY, *ARGS, FAKE_BODY=f'{{"version": "{SHA}"}}')
        self.assertEqual(run.code, 0, run.err)
        order = [next(i for i, call in enumerate(run.calls) if word in call)
                 for word in ("update-function-code", "publish-version", "update-alias")]
        self.assertEqual(order, sorted(order))
        self.assertIn("--name live", run.called("update-alias")[0])
        self.assertIn("--function-version 7", run.called("update-alias")[0])
        self.assertIn(f"s3://example-bucket/{SHA}/app.zip", run.called("s3 cp")[0])

    def test_a_changed_zip_fails_the_digest_check_before_any_deploy_command(self):
        self.box.store_artifact(zip_bytes=b"another zip")
        run = self.box.run(DEPLOY, *ARGS, FAKE_BODY=SHA)
        self.assertEqual(run.code, 1)
        self.assertIn("::error::", run.out + run.err)
        self.assertEqual(run.called("lambda"), [])
        self.assertEqual(run.called("curl"), [])

    def test_a_changed_zip_fails_the_digest_check_for_the_terraform_target_too(self):
        self.box.store_artifact(zip_bytes=b"another zip")
        run = self.box.run(DEPLOY, *ARGS, DEPLOY_TARGET="terraform", FAKE_BODY=SHA)
        self.assertEqual(run.code, 1)
        self.assertEqual(run.called("terraform"), [])

    def test_an_old_live_version_fails_the_version_check(self):
        run = self.box.run(DEPLOY, *ARGS, FAKE_BODY="0000000000000000000000000000000000000000",
                           VERIFY_TRIES="3")
        self.assertEqual(run.code, 1)
        self.assertIn("::error::", run.out + run.err)
        self.assertEqual(len(run.called("curl")), 3)

    def test_a_failing_endpoint_fails_the_version_check(self):
        run = self.box.run(DEPLOY, *ARGS, FAKE_CURL_FAIL="1", VERIFY_TRIES="2")
        self.assertEqual(run.code, 1)

    def test_the_terraform_success_path_plans_before_it_applies_and_calls_no_lambda_command(self):
        run = self.box.run(DEPLOY, *ARGS, DEPLOY_TARGET="terraform", FAKE_BODY=SHA)
        self.assertEqual(run.code, 0, run.err)
        plan = next(i for i, call in enumerate(run.calls) if call.startswith("terraform plan"))
        apply = next(i for i, call in enumerate(run.calls) if call.startswith("terraform apply"))
        self.assertLess(plan, apply)
        self.assertIn("-var zip_path=", run.calls[plan])
        self.assertIn("-var zip_path=", run.calls[apply])
        self.assertEqual(run.called("aws lambda"), [])

    def test_an_unknown_target_exits_one(self):
        run = self.box.run(DEPLOY, *ARGS, DEPLOY_TARGET="ecs", FAKE_BODY=SHA)
        self.assertEqual(run.code, 1)
        self.assertEqual(run.called("lambda"), [])
        self.assertEqual(run.called("terraform"), [])

    def test_an_empty_argument_exits_one_and_runs_no_tool(self):
        for position in range(4):
            args = list(ARGS)
            args[position] = ""
            run = self.box.run(DEPLOY, *args, FAKE_BODY=SHA)
            self.assertEqual(run.code, 1, position)
            self.assertIn("::error::", run.out + run.err)
            self.assertEqual(run.calls, [], position)


class CheckStaged(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox(self)

    def run_script(self, sha=SHA, **env):
        return self.box.run(STAGED, sha, GITHUB_REPOSITORY="example/repo", **env)

    def test_a_successful_staging_status_passes(self):
        run = self.run_script(FAKE_DEPLOY_IDS="11 12", FAKE_STATE="success")
        self.assertEqual(run.code, 0, run.err)
        self.assertIn(f"repos/example/repo/deployments?sha={SHA}&environment=staging", run.calls[0])

    def test_a_staging_record_with_no_success_fails(self):
        run = self.run_script(FAKE_DEPLOY_IDS="11 12", FAKE_STATE="failure")
        self.assertEqual(run.code, 1)
        self.assertIn("::error::", run.out + run.err)

    def test_no_staging_deployment_of_the_sha_fails(self):
        run = self.run_script(FAKE_DEPLOY_IDS="", FAKE_STATE="success")
        self.assertEqual(run.code, 1)

    def test_an_empty_sha_or_repository_exits_one_and_runs_no_tool(self):
        self.assertEqual(self.run_script(sha="").code, 1)
        run = self.box.run(STAGED, SHA)
        self.assertEqual(run.code, 1)
        self.assertEqual(run.calls, [])


if __name__ == "__main__":
    unittest.main()
