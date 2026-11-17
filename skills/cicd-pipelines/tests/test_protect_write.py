"""Tests of the protection write script, run as a command line with a fake `gh` on PATH.

The fake `gh` answers by method and path, in call order, and logs each body. No test reaches GitHub.
"""
import json
import os
import subprocess
import sys
import unittest

from fake_gh import Sandbox
from skill_files import SKILL

SCRIPT = os.path.join(SKILL, "scripts", "protect_write.py")
ENV = "repos/o/r/environments/prod"
RULESET = "repos/o/r/rulesets/7"
COLLECTION = "repos/o/r/rulesets"
POLICIES = "repos/o/r/environments/prod/deployment-branch-policies"


def environment_get(reviewers=False, wait=0):
    rules = [{"id": 1, "type": "wait_timer", "wait_timer": wait}]
    if reviewers:
        rules.append({"id": 2, "type": "required_reviewers", "prevent_self_review": True,
                      "reviewers": [{"type": "User", "reviewer": {"id": 42, "login": "alex"}}]})
    return {"id": 5, "name": "prod", "can_admins_bypass": True, "protection_rules": rules,
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}


def environment_shape(reviewers=False, wait=0):
    return {"wait_timer": wait, "prevent_self_review": reviewers,
            "reviewers": [{"type": "User", "id": 42}] if reviewers else [],
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}


def ruleset_get(enforcement="active"):
    return {"id": 7, "node_id": "n", "name": "main-protection", "target": "branch", "source": "o/r",
            "source_type": "Repository", "enforcement": enforcement, "current_user_can_bypass": "never",
            "_links": {}, "created_at": "t", "updated_at": "t", "bypass_actors": [], "conditions": None,
            "rules": [{"type": "deletion"}]}


def ruleset_shape(enforcement="active"):
    return {"name": "main-protection", "target": "branch", "enforcement": enforcement, "bypass_actors": [],
            "conditions": None, "rules": [{"type": "deletion"}]}


class Base(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def row(self, path, method, seen, proposed):
        name = os.path.join(self.box.root, f"row{len(os.listdir(self.box.root))}.json")
        with open(name, "w", encoding="utf-8") as handle:
            json.dump({"path": path, "method": method, "seen": seen, "proposed": proposed}, handle)
        return name

    def run_script(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], env=self.box.env(), capture_output=True, text=True)

    def writes(self):
        return self.box.bodies()


class Show(Base):
    def test_a_matching_object_prints_the_diff_and_writes_nothing(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get()}])
        row = self.row(ENV, "PUT", environment_shape(), environment_shape(reviewers=True))
        done = self.run_script("--show", row)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("+", done.stdout)
        self.assertIn('"prevent_self_review": true', done.stdout)
        self.assertEqual(self.writes(), [])

    def test_a_changed_object_stops_with_exit_1_and_no_write(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get(wait=30)}])
        row = self.row(ENV, "PUT", environment_shape(), environment_shape(reviewers=True))
        done = self.run_script("--show", row)
        self.assertEqual(done.returncode, 1)
        self.assertIn("changed", done.stdout)
        self.assertIn('"wait_timer": 30', done.stdout)
        self.assertEqual(self.writes(), [])

    def test_a_403_exits_2(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Forbidden (HTTP 403)"}])
        done = self.run_script("--show", self.row(ENV, "PUT", environment_shape(), environment_shape()))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout.strip(), "error: HTTP 403: gh: Forbidden (HTTP 403)")

    def test_a_404_with_a_seen_object_exits_2(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Not Found (HTTP 404)"}])
        done = self.run_script("--show", self.row(ENV, "PUT", environment_shape(), environment_shape()))
        self.assertEqual(done.returncode, 2)
        self.assertIn("HTTP 404", done.stdout)

    def test_a_404_for_an_absent_object_matches_and_the_diff_starts_from_null(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Not Found (HTTP 404)"}])
        done = self.run_script("--show", self.row(ENV, "PUT", None, environment_shape()))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("-null", done.stdout)

    def test_an_object_that_appeared_for_a_null_seen_exits_1(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get()}])
        done = self.run_script("--show", self.row(ENV, "PUT", None, environment_shape()))
        self.assertEqual(done.returncode, 1)

    def test_a_post_diff_starts_from_null_and_the_list_is_the_seen(self):
        listing = [{"id": 1, "name": "other", "target": "tag", "enforcement": "active", "node_id": "x"}]
        self.box.route_seq("GET", COLLECTION, [{"body": listing}])
        seen = [{"id": 1, "name": "other", "target": "tag", "enforcement": "active"}]
        done = self.run_script("--show", self.row(COLLECTION, "POST", seen, ruleset_shape()))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("-null", done.stdout)

    def test_a_bad_row_file_exits_2(self):
        name = os.path.join(self.box.root, "bad.json")
        with open(name, "w", encoding="utf-8") as handle:
            handle.write('{"path": "x"}')
        self.assertEqual(self.run_script("--show", name).returncode, 2)

    def test_a_missing_gh_exits_2(self):
        box = Sandbox(gh=False)
        self.addCleanup(box.cleanup)
        name = os.path.join(box.root, "row.json")
        with open(name, "w", encoding="utf-8") as handle:
            json.dump({"path": ENV, "method": "PUT", "seen": None, "proposed": {}}, handle)
        done = subprocess.run([sys.executable, SCRIPT, "--show", name], env=box.env(), capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("gh is not on PATH", done.stdout)


class Apply(Base):
    def test_a_clean_write_reads_writes_reads_again_and_passes(self):
        after = environment_get(reviewers=True)
        self.box.route_seq("GET", ENV, [{"body": environment_get()}, {"body": after}])
        self.box.route_seq("PUT", ENV, [{"body": after}])
        row = self.row(ENV, "PUT", environment_shape(), environment_shape(reviewers=True))
        done = self.run_script("--apply", row)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("written and verified", done.stdout)
        self.assertIn("before JSON:", done.stdout)
        self.assertEqual(len(self.writes()), 1)
        self.assertEqual(self.writes()[0]["body"], environment_shape(reviewers=True))
        calls = [call for call in self.box.calls() if "-X" in call]
        self.assertEqual(len(calls), 1)

    def test_a_changed_object_writes_nothing(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get(wait=30)}])
        done = self.run_script("--apply", self.row(ENV, "PUT", environment_shape(), environment_shape(True)))
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.writes(), [])

    def test_a_403_on_the_first_get_writes_nothing_and_exits_2(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Forbidden (HTTP 403)"}])
        done = self.run_script("--apply", self.row(ENV, "PUT", environment_shape(), environment_shape(True)))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.writes(), [])

    def test_a_404_on_the_first_get_writes_nothing_and_exits_2(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Not Found (HTTP 404)"}])
        done = self.run_script("--apply", self.row(ENV, "PUT", environment_shape(), environment_shape(True)))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.writes(), [])

    def test_a_422_write_prints_the_before_json_and_the_history_version(self):
        self.box.route_seq("GET", RULESET, [{"body": ruleset_get()}])
        self.box.route_seq("GET", RULESET + "/history", [{"body": [{"version_id": 12}, {"version_id": 11}]}])
        self.box.route_seq("PUT", RULESET, [{"exit": 1, "stderr": "gh: Validation Failed (HTTP 422)"}])
        done = self.run_script("--apply", self.row(RULESET, "PUT", ruleset_shape(), ruleset_shape("disabled")))
        self.assertEqual(done.returncode, 1)
        self.assertIn("HTTP 422", done.stdout)
        self.assertIn('"enforcement": "active"', done.stdout)
        self.assertIn("history version: 12", done.stdout)

    def test_a_mismatch_after_the_write_prints_the_before_json(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get()}, {"body": environment_get()}])
        self.box.route_seq("PUT", ENV, [{"body": {}}])
        done = self.run_script("--apply", self.row(ENV, "PUT", environment_shape(), environment_shape(True)))
        self.assertEqual(done.returncode, 1)
        self.assertIn("does not hold the proposed JSON", done.stdout)
        self.assertIn("before JSON:", done.stdout)
        self.assertNotIn("written and verified", done.stdout)

    def test_the_check_ignores_the_fields_that_only_a_get_holds(self):
        self.box.route_seq("GET", RULESET, [{"body": ruleset_get()}, {"body": ruleset_get("disabled")}])
        self.box.route_seq("GET", RULESET + "/history", [{"body": [{"version_id": 3}]}])
        self.box.route_seq("PUT", RULESET, [{"body": {}}])
        done = self.run_script("--apply", self.row(RULESET, "PUT", ruleset_shape(), ruleset_shape("disabled")))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("history version: 3", done.stdout)

    def test_a_history_that_cannot_be_read_is_unavailable(self):
        self.box.route_seq("GET", RULESET, [{"body": ruleset_get()}, {"body": ruleset_get("disabled")}])
        self.box.route_seq("PUT", RULESET, [{"body": {}}])
        done = self.run_script("--apply", self.row(RULESET, "PUT", ruleset_shape(), ruleset_shape("disabled")))
        self.assertEqual(done.returncode, 0)
        self.assertIn("history version: unavailable", done.stdout)

    def test_an_absent_environment_is_written(self):
        after = environment_get(reviewers=True)
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Not Found (HTTP 404)"}, {"body": after}])
        self.box.route_seq("PUT", ENV, [{"body": after}])
        done = self.run_script("--apply", self.row(ENV, "PUT", None, environment_shape(reviewers=True)))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(self.writes()), 1)

    def test_a_new_ruleset_is_a_post_and_is_checked_by_its_id(self):
        self.box.route_seq("GET", COLLECTION, [{"body": []}])
        self.box.route_seq("POST", COLLECTION, [{"body": {"id": 9}}])
        self.box.route_seq("GET", "repos/o/r/rulesets/9", [{"body": dict(ruleset_get(), id=9)}])
        done = self.run_script("--apply", self.row(COLLECTION, "POST", [], ruleset_shape()))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.writes()[0]["method"], "POST")
        self.assertNotIn("history version", done.stdout)

    def test_a_post_answer_with_no_id_is_a_stop(self):
        self.box.route_seq("GET", COLLECTION, [{"body": []}])
        self.box.route_seq("POST", COLLECTION, [{"body": {}}])
        done = self.run_script("--apply", self.row(COLLECTION, "POST", [], ruleset_shape()))
        self.assertEqual(done.returncode, 1)
        self.assertIn("no id", done.stdout)

    def test_a_failed_get_after_the_write_is_a_stop_with_exit_1(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get()},
                                        {"exit": 1, "stderr": "gh: Server Error (HTTP 502)"}])
        self.box.route_seq("PUT", ENV, [{"body": {}}])
        done = self.run_script("--apply", self.row(ENV, "PUT", environment_shape(), environment_shape(True)))
        self.assertEqual(done.returncode, 1)
        self.assertIn("check after it failed", done.stdout)
        self.assertIn("before JSON:", done.stdout)

    def test_a_policy_is_created_and_checked_by_its_id(self):
        self.box.route_seq("GET", POLICIES, [{"body": {"total_count": 0, "branch_policies": []}}])
        self.box.route_seq("POST", POLICIES, [{"body": {"id": 3}}])
        self.box.route_seq("GET", POLICIES + "/3", [{"body": {"id": 3, "node_id": "n", "name": "main", "type": "branch"}}])
        done = self.run_script("--apply", self.row(POLICIES, "POST", [], {"name": "main", "type": "branch"}))
        self.assertEqual(done.returncode, 0, done.stdout)


class Read(Base):
    def test_it_prints_the_write_shape_of_an_environment(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get(reviewers=True)}])
        done = self.run_script("--read", ENV)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(json.loads(done.stdout), environment_shape(reviewers=True))

    def test_the_rulesets_list_keeps_the_id_and_drops_the_rest(self):
        pages = json.dumps([{"id": 1, "name": "a", "target": "branch", "enforcement": "active", "node_id": "x"}])
        pages += json.dumps([{"id": 2, "name": "b", "target": "tag", "enforcement": "active"}])
        self.box.route_seq("GET", COLLECTION, [{"body": pages}])
        done = self.run_script("--read", COLLECTION)
        self.assertEqual(done.returncode, 0)
        self.assertEqual([item["id"] for item in json.loads(done.stdout)], [1, 2])
        self.assertEqual(set(json.loads(done.stdout)[0]), {"id", "name", "target", "enforcement"})

    def test_the_policies_list_is_reduced_to_id_name_and_type(self):
        body = {"total_count": 1, "branch_policies": [{"id": 3, "node_id": "n", "name": "main", "type": "branch"}]}
        self.box.route_seq("GET", POLICIES, [{"body": body}])
        done = self.run_script("--read", POLICIES)
        self.assertEqual(json.loads(done.stdout), [{"id": 3, "name": "main", "type": "branch"}])

    def test_any_other_path_prints_the_raw_json(self):
        self.box.route_seq("GET", "users/alex", [{"body": {"id": 42, "login": "alex", "type": "User"}}])
        done = self.run_script("--read", "users/alex")
        self.assertEqual(json.loads(done.stdout)["id"], 42)

    def test_a_404_exits_2_and_with_absent_ok_prints_null(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Not Found (HTTP 404)"}])
        self.assertEqual(self.run_script("--read", ENV).returncode, 2)
        done = self.run_script("--read", ENV, "--absent-ok")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "null"))

    def test_a_403_exits_2_even_with_absent_ok(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: Forbidden (HTTP 403)"}])
        self.assertEqual(self.run_script("--read", ENV, "--absent-ok").returncode, 2)

    def test_an_error_with_no_code_says_unknown(self):
        self.box.route_seq("GET", ENV, [{"exit": 1, "stderr": "gh: not logged in"}])
        done = self.run_script("--read", ENV)
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stdout.startswith("error: HTTP unknown:"))

    def test_a_read_makes_no_write_call(self):
        self.box.route_seq("GET", ENV, [{"body": environment_get()}])
        self.run_script("--read", ENV)
        self.assertEqual([call for call in self.box.calls() if "-X" in call], [])


class Usage(Base):
    def test_no_mode_exits_2(self):
        self.assertEqual(self.run_script().returncode, 2)

    def test_two_modes_exit_2(self):
        self.assertEqual(self.run_script("--show", "--apply").returncode, 2)


if __name__ == "__main__":
    unittest.main()
