import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
GRADER = os.path.join(SKILL_DIR, "graders", "grade_setup.py")

RULES_TEXT = """\
# SQL rules

```toml
[style]
indent = "2 spaces"

[formatter]
tool = "none"

[sources]
tags = ["sql", "tx"]

[rules]
disabled = []
```

## Repo rules

- Name every column.
"""
ALLOW_TEXT = '["example.com/acme/shop"]\nservices = ["app-dev"]\n'
DIGEST = "a" * 64
PLAN = {
    "ok": True,
    "rules_file": {
        "path": "/r/docs/agents/sql.md",
        "diff": "--- a/docs/agents/sql.md\n+++ b/docs/agents/sql.md\n@@ -0,0 +1,3 @@\n+# SQL rules\n+\n+- Name every column.\n",
        "text": RULES_TEXT,
    },
    "allowlist": {
        "path": "/h/sql-skill/allowlist.toml",
        "diff": "+++ b\n+services = [\"app-dev\"]\n",
        "text": ALLOW_TEXT,
    },
    "digest": DIGEST,
}
SHOWN = "Here is the diff: # SQL rules and - Name every column. and services = [\"app-dev\"]"


def assistant(*items):
    return {"type": "assistant", "message": {"content": list(items)}}


def text(value):
    return {"type": "text", "text": value}


def call(identifier, name, **data):
    return {"type": "tool_use", "id": identifier, "name": name, "input": data}


def result(identifier, content):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": identifier, "content": content}]}}


def plan_steps(identifier="p1", plan=None):
    return [
        assistant(call(identifier, "Bash", command="python3 setup_files.py plan /r --proposal /tmp/p.json")),
        result(identifier, json.dumps(plan or PLAN)),
    ]


def write_call(identifier="w1", digest=DIGEST):
    return assistant(call(identifier, "Bash", command="python3 setup_files.py write /r --proposal /tmp/p.json --confirm " + digest))


GOOD = plan_steps() + [assistant(text(SHOWN)), write_call()]


class GraderCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(os.path.join(self.repo, "docs", "agents"))
        self.allowlist = os.path.join(self.tmp, "allowlist.toml")
        self.expect = {
            "settings": {"sources": {"tags": ["tx", "sql"]}, "formatter": {"tool": "none"}},
            "contains": ["- Name every column."],
            "absent": ["Never use SELECT star."],
            "unchanged_lines": ["# SQL rules"],
            "services": ["app-dev"],
        }
        self.put_files(RULES_TEXT, ALLOW_TEXT)

    def put_files(self, rules, allowlist):
        if rules is None:
            if os.path.exists(self.rules_path):
                os.remove(self.rules_path)
        else:
            with open(self.rules_path, "w", encoding="utf-8") as handle:
                handle.write(rules)
        if allowlist is not None:
            with open(self.allowlist, "w", encoding="utf-8") as handle:
                handle.write(allowlist)

    @property
    def rules_path(self):
        return os.path.join(self.repo, "docs", "agents", "sql.md")

    def trace(self, lines):
        path = os.path.join(self.tmp, "trace.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(json.dumps(line) for line in lines) + "\n")
        return path

    def grade(self, lines, expect=None, allowlist=True, trace=None):
        expect_path = os.path.join(self.tmp, "expect.json")
        with open(expect_path, "w", encoding="utf-8") as handle:
            json.dump(self.expect if expect is None else expect, handle)
        args = [trace or self.trace(lines), "--repo", self.repo, "--expect", expect_path]
        if allowlist:
            args += ["--allowlist", self.allowlist, "--key", "example.com/acme/shop"]
        done = subprocess.run([sys.executable, "-I", GRADER, *args], capture_output=True, text=True)
        return done.returncode, done.stdout, done.stderr


class PassTest(GraderCase):
    def test_a_good_run_passes(self):
        code, out, err = self.grade(GOOD)
        self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), (out, err))

    def test_a_write_tool_call_with_the_plan_text_passes(self):
        lines = plan_steps() + [
            assistant(text(SHOWN)),
            assistant(call("w", "Write", file_path="/r/docs/agents/sql.md", content=RULES_TEXT)),
            assistant(call("w2", "Write", file_path="/h/sql-skill/allowlist.toml", content=ALLOW_TEXT)),
        ]
        self.assertEqual(self.grade(lines)[0], 0)

    def test_a_plan_result_in_a_text_item_and_a_pretty_printed_json_pass(self):
        lines = plan_steps(plan=None)
        lines[1] = result("p1", [{"type": "text", "text": json.dumps(PLAN, indent=2)}])
        self.assertEqual(self.grade(lines + GOOD[2:])[0], 0)

    def test_no_allowlist_expectation(self):
        os.remove(self.allowlist)
        code, out, _ = self.grade(GOOD, expect={"no_allowlist": True, "settings": {"formatter": {"tool": "none"}}})
        self.assertEqual(code, 0, out)

    def test_written_false_with_no_file_and_no_change_call(self):
        self.put_files(None, None)
        os.remove(self.allowlist)
        code, out, _ = self.grade(plan_steps(), expect={"written": False, "no_allowlist": True})
        self.assertEqual(code, 0, out)


class FailTest(GraderCase):
    def failures(self, lines, **kwargs):
        code, out, err = self.grade(lines, **kwargs)
        self.assertEqual(code, 1, (out, err))
        found = out.strip().splitlines()
        self.assertEqual(found[-1], "FAIL")
        return found[:-1]

    def test_a_write_before_plan_fails_order(self):
        self.assertEqual(
            [line.split(":")[0] for line in self.failures([write_call()])], ["FAIL order"]
        )

    def test_a_write_tool_call_before_plan_fails_order(self):
        lines = [assistant(call("w", "Write", file_path="/r/docs/agents/sql.md", content=RULES_TEXT))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL order"))

    def test_a_bash_redirect_naming_the_file_is_a_change_call(self):
        lines = [assistant(call("b", "Bash", command="cat x > docs/agents/sql.md"))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL order"))
        lines = [assistant(call("b", "Bash", command="sed -i s/a/b/ docs/agents/sql.md"))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL order"))
        lines = [assistant(call("b", "Bash", command="cp x ~/.config/sql-skill/allowlist.toml"))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL order"))

    def test_a_read_with_a_redirect_to_dev_null_is_no_change_call(self):
        for command in ("cat docs/agents/sql.md 2>/dev/null", "grep x docs/agents/sql.md > /dev/null", "cat docs/agents/sql.md 2>&1"):
            with self.subTest(command=command):
                lines = [assistant(call("r", "Bash", command=command))]
                self.put_files(None, None)
                code, out, _ = self.grade(lines, expect={"written": False}, allowlist=False)
                self.assertEqual((code, out.strip().splitlines()[-1]), (0, "PASS"), out)

    def test_a_read_of_the_file_is_no_change_call(self):
        lines = GOOD + [assistant(call("r", "Bash", command="cat docs/agents/sql.md"))]
        self.assertEqual(self.grade(lines)[0], 0)

    def test_a_write_after_a_plan_but_without_the_shown_diff_fails_shown(self):
        lines = plan_steps() + [assistant(text("Writing now.")), write_call()]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL shown"))

    def test_the_diff_shown_before_the_plan_does_not_count(self):
        lines = [assistant(text(SHOWN))] + plan_steps() + [write_call()]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL shown"))

    def test_a_write_with_the_wrong_or_no_digest_fails_digest(self):
        lines = plan_steps() + [assistant(text(SHOWN)), write_call(digest="b" * 64)]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL digest"))
        lines = plan_steps() + [assistant(text(SHOWN)), assistant(call("w", "Bash", command="python3 setup_files.py write /r --proposal p"))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL digest"))

    def test_a_write_tool_call_with_other_content_fails_digest(self):
        lines = plan_steps() + [assistant(text(SHOWN)), assistant(call("w", "Write", file_path="/r/docs/agents/sql.md", content=RULES_TEXT + "x"))]
        self.assertTrue(self.failures(lines)[0].startswith("FAIL digest"))

    def test_a_toml_value_that_differs_fails_toml(self):
        self.expect["settings"]["formatter"]["tool"] = "prettier-plugin-embed"
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL toml"))

    def test_a_missing_section_or_key_fails_toml(self):
        self.expect["settings"] = {"style": {"comma": "trailing"}}
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL toml"))

    def test_contains_and_absent(self):
        self.expect["contains"] = ["- Another rule."]
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL toml"))
        self.expect["contains"] = []
        self.expect["absent"] = ["Name every column."]
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL toml"))

    def test_contains_takes_a_rule_text_without_its_marker(self):
        self.expect["contains"] = ["Name every column."]
        self.assertEqual(self.grade(GOOD)[0], 0)

    def test_a_malformed_rules_file_fails_toml(self):
        self.put_files("# x\n\n```toml\n[style\n```\n", None)
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL toml"))

    def test_written_false_with_a_change_call_or_a_file_fails(self):
        self.expect = {"written": False}
        found = self.failures(GOOD, allowlist=False)
        self.assertTrue(any(line.startswith("FAIL order") for line in found))
        self.assertTrue(any(line.startswith("FAIL toml") for line in found))

    def test_a_missing_unchanged_line_fails_unchanged(self):
        self.expect["unchanged_lines"] = ["a hand-written line that is gone"]
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL unchanged"))

    def test_the_allowlist_services_and_the_no_allowlist_expectation(self):
        self.expect["services"] = ["other"]
        self.assertTrue(self.failures(GOOD)[0].startswith("FAIL allowlist"))
        del self.expect["services"]
        self.expect["no_allowlist"] = True
        self.assertIn("FAIL allowlist: an entry exists for example.com/acme/shop", self.failures(GOOD))


class UsageTest(GraderCase):
    def test_an_unreadable_trace_is_exit_2(self):
        bad = os.path.join(self.tmp, "bad.jsonl")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("not json\n")
        for path in (bad, os.path.join(self.tmp, "missing.jsonl")):
            with self.subTest(path=os.path.basename(path)):
                code, out, err = self.grade([], trace=path)
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.strip())

    def test_a_trace_with_no_assistant_line_is_exit_2(self):
        code, out, err = self.grade([{"type": "system"}])
        self.assertEqual((code, out), (2, ""))

    def test_expect_misuse_is_exit_2(self):
        for expect in (
            {"services": ["a"], "no_allowlist": True},
            {"bogus": 1},
            {"written": "yes"},
            {"settings": []},
        ):
            with self.subTest(expect=expect):
                self.assertEqual(self.grade(GOOD, expect=expect)[0], 2)
        self.assertEqual(self.grade(GOOD, allowlist=False)[0], 2)  # services without --allowlist

    def test_the_trace_can_come_from_stdin(self):
        expect_path = os.path.join(self.tmp, "expect.json")
        with open(expect_path, "w", encoding="utf-8") as handle:
            json.dump({"settings": {"formatter": {"tool": "none"}}}, handle)
        done = subprocess.run(
            [sys.executable, "-I", GRADER, "-", "--repo", self.repo, "--expect", expect_path],
            input="\n".join(json.dumps(line) for line in GOOD), capture_output=True, text=True,
        )
        self.assertEqual(done.returncode, 0, done.stdout)


class RoundThreeGraderTest(GraderCase):
    def test_a_clobber_redirect_naming_the_file_is_a_change_call(self):
        for command in ("echo x >| docs/agents/sql.md", "echo x >|allowlist.toml"):
            with self.subTest(command=command):
                lines = [assistant(call("b", "Bash", command=command))]
                code, out, err = self.grade(lines)
                self.assertEqual(code, 1, (out, err))
                self.assertTrue(out.strip().splitlines()[0].startswith("FAIL order"), out)


class ServicesAndPlanInOneResultTest(GraderCase):
    """One Bash call that runs `services` and then `plan` has two JSON objects that start with ok: the plan is the one
    with a digest (ticket 509: a real run read the services object, so `shown` and `digest` were checked on the wrong object)."""

    def combined(self, shown):
        services = json.dumps({"ok": True, "service_check": {"service_file": "found", "missing": []}})
        return [
            assistant(call("p1", "Bash", command="python3 setup_files.py services app-dev\npython3 setup_files.py plan /r --proposal /tmp/p.json")),
            result("p1", services + " " + json.dumps(PLAN)),
            assistant(text(shown)),
            write_call(),
        ]

    def test_the_plan_object_is_the_one_with_the_digest(self):
        code, out, err = self.grade(self.combined(SHOWN))
        self.assertEqual(code, 0, (out, err))

    def test_a_missing_diff_is_found_on_the_plan_object_not_the_services_object(self):
        code, out, err = self.grade(self.combined("I will write now."))
        self.assertEqual(code, 1, (out, err))
        self.assertTrue(any(line.startswith("FAIL shown") for line in out.splitlines()), out)


if __name__ == "__main__":
    unittest.main()
