"""Tests of scripts/check_pins.py through its command line, with a fake `gh` on PATH (see fake_gh.py)."""
import json
import os
import subprocess
import sys
import unittest

from fake_gh import Sandbox
from skill_files import SKILL

SCRIPT = os.path.join(SKILL, "scripts", "check_pins.py")
GOOD, OTHER, TAG_OBJECT = "a" * 40, "b" * 40, "c" * 40
REPO = "repos/acme/setup"


def workflow(*lines):
    return {".github/workflows/ci.yml": "jobs:\n  test:\n    steps:\n" + "".join(f"      - uses: {x}\n" for x in lines)}


class CheckPins(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.box.route(REPO, {})

    def check(self, *lines, box=None):
        box = box or self.box
        done = subprocess.run([sys.executable, SCRIPT, box.repo(workflow(*lines))], env=box.env(),
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def tag(self, name, sha, kind="commit"):
        self.box.route(f"{REPO}/git/ref/tags/{name}", {"object": {"type": kind, "sha": sha}})

    def commit(self, sha):
        self.box.route(f"{REPO}/commits/{sha}", {"sha": sha})

    def result(self, *lines):
        out = self.check(*lines)
        return out["pins"][0]["result"], out["status"]

    def test_a_tag_that_resolves_to_the_pinned_sha_is_ok(self):
        self.tag("v1.2.0", GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0"), ("ok", "verified"))

    def test_an_annotated_tag_is_dereferenced_to_its_commit(self):
        self.tag("v1.2.0", TAG_OBJECT, "tag")
        self.box.route(f"{REPO}/git/tags/{TAG_OBJECT}", {"object": {"type": "commit", "sha": GOOD}})
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0")[0], "ok")

    def test_a_tag_of_a_tag_is_dereferenced_down_to_its_commit(self):
        self.tag("v1.2.0", TAG_OBJECT, "tag")
        self.box.route(f"{REPO}/git/tags/{TAG_OBJECT}", {"object": {"type": "tag", "sha": OTHER}})
        self.box.route(f"{REPO}/git/tags/{OTHER}", {"object": {"type": "commit", "sha": GOOD}})
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0"), ("ok", "verified"))

    def test_a_tag_that_resolves_to_another_commit_is_a_mismatch(self):
        self.tag("v1.2.0", OTHER)
        self.commit(GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0"), ("tag-mismatch", "verified"))

    def test_a_sha_that_is_not_a_commit_of_the_repo_is_unknown(self):
        self.tag("v1.2.0", OTHER)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0")[0], "unknown-commit")

    def test_the_422_that_github_gives_for_a_sha_that_is_not_in_the_repo_is_an_unknown_commit(self):
        self.tag("v1.2.0", OTHER)
        self.box.route(f"{REPO}/commits/{GOOD}", "", exit=1, stderr=f"gh: No commit found for SHA: {GOOD} (HTTP 422)")
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0"), ("unknown-commit", "verified"))

    def test_a_missing_tag_with_a_real_commit_is_an_unknown_tag(self):
        self.commit(GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v9.9.9")[0], "unknown-tag")

    def test_without_a_version_comment_only_the_commit_is_checked(self):
        self.commit(GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD}")[0], "ok")
        self.assertEqual(self.result(f"acme/setup@{OTHER}")[0], "unknown-commit")

    def test_a_reusable_workflow_path_checks_the_repo_of_the_action(self):
        self.tag("v2", GOOD)
        pin = self.check(f"acme/setup/.github/workflows/x.yml@{GOOD} # v2")["pins"][0]
        self.assertEqual((pin["uses"], pin["result"]), ("acme/setup/.github/workflows/x.yml", "ok"))

    def test_tag_pins_local_actions_and_docker_images_are_not_checked(self):
        out = self.check("acme/setup@v4", "./local", "docker://alpine@sha256:" + GOOD)
        self.assertEqual(out["pins"], [])
        self.assertEqual(self.box.calls(), [])

    def test_each_repo_and_tag_is_looked_up_once_with_get_calls_only(self):
        self.tag("v1.2.0", GOOD)
        self.check(f"acme/setup@{GOOD} # v1.2.0", f"acme/setup@{GOOD} # v1.2.0")
        calls = self.box.calls()
        self.assertEqual(calls, [["api", REPO], ["api", f"{REPO}/git/ref/tags/v1.2.0"]])

    def test_a_gh_failure_is_unverified_with_its_reason_and_never_a_finding(self):
        cases = {
            "not-logged-in": "To get started with GitHub CLI, please run:  gh auth login",
            "no-network": "error connecting to api.github.com",
            "rate-limited": "gh: API rate limit exceeded (HTTP 403)",
            "gh-error": "boom",
        }
        for reason, message in cases.items():
            with self.subTest(reason=reason):
                open(self.box.log, "w").close()
                self.box.route(REPO, "", exit=4, stderr=message)
                out = self.check(f"acme/setup@{GOOD} # v1", f"acme/other@{GOOD} # v1")
                self.assertEqual(out["status"], "unverified")
                self.assertEqual(out["unverified_reasons"], [reason])
                self.assertEqual({p["result"] for p in out["pins"]}, {"unverified"})
                self.assertEqual(len(self.box.calls()), 1)

    def test_an_answer_of_an_unexpected_shape_is_unverified_and_the_same_commit_is_looked_up_once(self):
        self.box.route(f"{REPO}/git/ref/tags/v1", {"unexpected": True})
        out = self.check(f"acme/setup@{GOOD} # v1")
        self.assertEqual((out["status"], out["unverified_reasons"]), ("unverified", ["gh-error"]))
        self.tag("v2", OTHER)
        self.commit(GOOD)
        self.check(f"acme/setup@{GOOD} # v2", f"acme/setup@{GOOD} # v3")
        self.assertEqual(self.box.calls().count(["api", f"{REPO}/commits/{GOOD}"]), 1)

    def test_a_200_answer_that_is_not_an_object_is_unverified_and_never_a_finding(self):
        for body in ("null", "[]"):
            with self.subTest(body=body):
                self.box.route(f"{REPO}/commits/{GOOD}", body)
                self.assertEqual(self.result(f"acme/setup@{GOOD}"), ("unverified", "unverified"))
        for body in ({"object": None}, {"object": {}}):
            with self.subTest(body=body):
                self.tag("v1", OTHER)
                self.box.route(f"{REPO}/git/ref/tags/v1", body)
                self.commit(GOOD)
                self.assertEqual(self.result(f"acme/setup@{GOOD} # v1"), ("unverified", "unverified"))

    def test_an_annotated_tag_whose_object_cannot_be_read_is_unverified(self):
        self.tag("v1.2.0", TAG_OBJECT, "tag")
        self.commit(GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # v1.2.0"), ("unverified", "unverified"))

    def test_a_version_comment_that_equals_the_sha_does_not_hide_a_real_commit(self):
        self.commit(GOOD)
        self.assertEqual(self.result(f"acme/setup@{GOOD} # {GOOD}"), ("unknown-tag", "verified"))

    def test_a_missing_gh_is_unverified(self):
        box = Sandbox(gh=False)
        self.addCleanup(box.cleanup)
        out = self.check(f"acme/setup@{GOOD} # v1", box=box)
        self.assertEqual((out["status"], out["unverified_reasons"]), ("unverified", ["gh-missing"]))

    def test_an_unreadable_repo_is_unverified_and_the_next_repo_is_still_checked(self):
        self.box.route("repos/acme/other", {})
        self.box.route(f"repos/acme/other/commits/{GOOD}", {})
        self.box.route(REPO, "", exit=1, stderr="gh: Not Found (HTTP 404)")
        out = self.check(f"acme/setup@{GOOD}", f"acme/other@{GOOD}")
        self.assertEqual([(p["result"], p.get("reason")) for p in out["pins"]],
                         [("unverified", "repo-unreadable"), ("ok", None)])

    def test_a_usage_error_exits_2(self):
        done = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
