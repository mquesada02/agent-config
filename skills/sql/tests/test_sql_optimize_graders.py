import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
GRADERS = os.path.join(SKILL_DIR, "graders")
LABEL = "Rewrite (unproven: no database):"


def run(script, args=(), stdin=None):
    """Run a grader command. Returns (exit code, stdout lines, stderr)."""
    proc = subprocess.run(
        [sys.executable, "-I", os.path.join(GRADERS, script), *args],
        input=stdin, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout.splitlines(), proc.stderr


def table(heading, rows):
    head = [f"## {heading}", "| # | Rule | Where | Problem | Fix |", "|---|---|---|---|---|"]
    return "\n".join(head + [f"| {' | '.join(row)} |" for row in rows])


GOOD = "\n".join([
    "# sql optimize: orders.ts",
    "**Result: 1 critical, 1 required, 2 suggestions.**",
    "",
    table("Critical", [["1", "PGJS-01", "orders.ts:10", "Extra parentheses in IN.", "Use IN ${sql(ids)}."]]),
    "",
    table("Required", [["2", "PG-03", "orders.ts:20, orders.ts:30-32", "Cast on the column.", "Cast the value."]]),
    "",
    table("Suggestions", [
        ["3", "PG-08", "orders.ts:40", "SELECT * in a template.", "List the columns."],
        ["4", "PG-09", "orders.ts:50", "Correlated subquery.",
         f"{LABEL} SELECT 1 FROM t. Run a database diff."],
    ]),
    "",
    "## Approve",
    "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.",
    "",
])

WITH_DISABLED = GOOD.replace(
    "**Result: 1 critical, 1 required, 2 suggestions.**\n",
    "**Result: 1 critical, 1 required, 2 suggestions.**\nDisabled rules: PG-10, PG-06.\n"
    "Note: PG-05 is disabled with no reason, so it stays enabled.\n",
)

EMPTY = "\n".join([
    "# sql optimize: the query",
    "**Result: 0 critical, 0 required, 0 suggestions.**",
    "",
    "## Approve",
    "There is nothing to approve.",
    "",
])


class RuleIdGraderTest(unittest.TestCase):
    def grade(self, text, *args):
        return run("grade_rule_ids.py", ["-", *args], text)

    def test_with_no_flags_a_readable_report_passes(self):
        code, out, _ = self.grade(GOOD)
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_expect_found_passes(self):
        code, out, _ = self.grade(GOOD, "--expect", "PGJS-01", "PG-08")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_expect_missing_fails_with_a_line(self):
        code, out, _ = self.grade(GOOD, "--expect", "PG-01")
        self.assertEqual(code, 1)
        self.assertEqual(out[-1], "FAIL")
        self.assertTrue(out[0].startswith("FAIL expect:PG-01:"), out)

    def test_forbid_found_fails_and_forbid_absent_passes(self):
        code, out, _ = self.grade(GOOD, "--forbid", "PG-03")
        self.assertEqual(code, 1)
        self.assertTrue(out[0].startswith("FAIL forbid:PG-03:"), out)
        code, out, _ = self.grade(GOOD, "--forbid", "PG-10")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_an_id_only_in_prose_is_not_found(self):
        text = GOOD.replace("# sql optimize: orders.ts", "# sql optimize: orders.ts\nNote: PG-01 is mentioned here.")
        code, out, _ = self.grade(text, "--expect", "PG-01")
        self.assertEqual(code, 1)
        code, out, _ = self.grade(text, "--forbid", "PG-01")
        self.assertEqual(code, 0)

    def test_a_row_with_an_escaped_pipe_in_a_cell_is_read(self):
        text = table("Critical", [["1", "PG-02", "a.ts:1", r"A \| B", "Fix."]])
        code, out, _ = self.grade(text, "--expect", "PG-02")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_the_header_and_separator_rows_are_not_rules(self):
        code, out, _ = self.grade(GOOD, "--forbid", "Rule", "Where", "#")
        self.assertEqual((code, out), (0, ["PASS"]))

    def test_an_unreadable_report_exits_2_with_no_verdict_line(self):
        code, out, err = run("grade_rule_ids.py", ["/no/such/report.md"])
        self.assertEqual(code, 2)
        self.assertEqual(out, [])
        self.assertTrue(err.strip())

    def test_a_path_argument_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(GOOD)
            code, out, _ = run("grade_rule_ids.py", [path, "--expect", "PG-09"])
        self.assertEqual((code, out), (0, ["PASS"]))


def assistant(*calls):
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "ok"}] + [
            {"type": "tool_use", "name": name, "input": data} for name, data in calls
        ]},
    })


def bash(command):
    return assistant(("Bash", {"command": command}))


RESULT_LINE = json.dumps({"type": "result", "result": "done"})


class NoChangeGraderTest(unittest.TestCase):
    def grade(self, *lines):
        return run("grade_no_change.py", ["-"], "\n".join(lines) + "\n")

    def assert_pass(self, *lines):
        code, out, _ = self.grade(*lines)
        self.assertEqual((code, out), (0, ["PASS"]), lines)

    def assert_fail(self, *lines):
        code, out, _ = self.grade(*lines)
        self.assertEqual(code, 1, lines)
        self.assertEqual(out[-1], "FAIL")
        self.assertTrue(out[0].startswith("FAIL change:"), out)

    def test_a_trace_with_reads_only_passes(self):
        self.assert_pass(
            assistant(("Read", {"file_path": "a.ts"}), ("Grep", {"pattern": "sql"})),
            bash("python3 scripts/extract.py invoice-format.ts"),
            RESULT_LINE,
        )

    def test_edit_write_and_notebook_edit_fail(self):
        for tool in ("Edit", "Write", "NotebookEdit"):
            with self.subTest(tool=tool):
                self.assert_fail(assistant((tool, {"file_path": "a.ts"})), RESULT_LINE)

    def test_each_file_changing_bash_form_fails(self):
        for command in (
            "mv a b", "cp a b", "rm a", "patch -p1 < x.diff", "echo x | tee a",
            "sed -i 's/a/b/' f", "sed -Ei 's/a/b/' f", "sed -ni p f", "sed -i.bak 's/a/b/' f",
            "sed -i'' 's/a/b/' f", "sed --in-place 's/a/b/' f", "sed --in-place=.bak 's/a/b/' f",
            "echo x > out.txt", "echo x >> out.txt", "echo x 2> err.txt", "echo x &> out.txt",
            "FOO=1 rm a", "sudo rm a", "env FOO=1 mv a b", "/bin/rm a",
            "cat a | sed -i s/a/b/ f", "ls && rm a", "ls; rm a", "ls & rm a", "ls\nrm a", "ls || cp a b",
        ):
            with self.subTest(command=command):
                self.assert_fail(bash(command), RESULT_LINE)

    def test_descriptor_copies_and_dev_null_are_not_changes(self):
        for command in (
            "python3 x.py 2>&1", "python3 x.py >&2", "python3 x.py &>/dev/null",
            "python3 x.py > /dev/null", "python3 x.py 2>/dev/null", "python3 x.py >>/dev/null 2>&1",
            "python3 x.py 2>&1 | head", "grep sql a.ts | wc -l", "sed -n 1,5p f", "sed -e p f",
        ):
            with self.subTest(command=command):
                self.assert_pass(bash(command), RESULT_LINE)

    def test_a_file_name_that_holds_rm_cp_or_tee_is_not_a_match(self):
        for command in ("cat form.ts", "cat copy.ts", "ls committee/", "grep x term/cpu.ts", "cat /tmp/rm/a"):
            with self.subTest(command=command):
                self.assert_pass(bash(command), RESULT_LINE)

    def test_a_change_after_a_pipe_fails(self):
        self.assert_fail(bash("cat a.ts | tee b.ts"), RESULT_LINE)

    def test_a_quoted_gt_is_the_accepted_false_fail(self):
        self.assert_fail(bash("grep '>' a.ts"), RESULT_LINE)

    def test_any_changing_call_among_many_fails(self):
        self.assert_fail(assistant(("Read", {"file_path": "a"})), bash("ls"), bash("rm a"), RESULT_LINE)

    def test_a_non_json_line_exits_2_with_no_verdict_line(self):
        code, out, err = self.grade(assistant(("Read", {})), "not json", RESULT_LINE)
        self.assertEqual((code, out), (2, []))
        self.assertTrue(err.strip())

    def test_a_trace_with_no_assistant_line_exits_2(self):
        code, out, err = self.grade(RESULT_LINE)
        self.assertEqual((code, out), (2, []))
        self.assertTrue(err.strip())

    def test_a_missing_trace_file_exits_2(self):
        code, out, _ = run("grade_no_change.py", ["/no/such/trace.jsonl"])
        self.assertEqual((code, out), (2, []))

    def test_a_path_argument_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "trace.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(bash("ls") + "\n" + RESULT_LINE + "\n")
            code, out, _ = run("grade_no_change.py", [path])
        self.assertEqual((code, out), (0, ["PASS"]))


class ReportGraderTest(unittest.TestCase):
    def grade(self, text, *args):
        return run("grade_report.py", ["-", *args], text)

    def assert_pass(self, text, *args):
        code, out, _ = self.grade(text, *args)
        self.assertEqual((code, out), (0, ["PASS"]), out)

    def assert_check(self, text, check, *args):
        code, out, _ = self.grade(text, *args)
        self.assertEqual(code, 1)
        self.assertEqual(out[-1], "FAIL")
        self.assertTrue(any(line.startswith(f"FAIL {check}:") for line in out), out)

    def test_a_good_report_passes(self):
        self.assert_pass(GOOD)

    def test_a_good_report_with_a_rewrite_row_and_a_disabled_line_passes(self):
        self.assert_pass(WITH_DISABLED)
        self.assert_pass(WITH_DISABLED, "--disabled", "PG-10", "PG-06")

    def test_a_report_with_no_finding_passes(self):
        self.assert_pass(EMPTY)

    def test_singular_suggestion_is_accepted(self):
        text = GOOD.replace("2 suggestions.", "2 suggestion.")
        self.assert_pass(text)

    def test_a_missing_title_fails(self):
        self.assert_check(GOOD.replace("# sql optimize: orders.ts", "# report"), "title")

    def test_a_missing_summary_fails(self):
        self.assert_check(GOOD.replace("**Result: 1 critical, 1 required, 2 suggestions.**\n", ""), "summary")

    def test_counts_that_differ_from_the_rows_fail(self):
        self.assert_check(GOOD.replace("1 critical, 1 required", "2 critical, 1 required"), "counts")

    def test_a_table_with_a_zero_count_fails(self):
        self.assert_check(GOOD.replace("1 critical, 1 required", "0 critical, 1 required"), "tables")

    def test_a_wrong_severity_order_fails(self):
        text = "\n".join([
            "# sql optimize: a.ts", "**Result: 1 critical, 1 required, 0 suggestions.**", "",
            table("Required", [["1", "PG-03", "a.ts:1", "p", "f"]]), "",
            table("Critical", [["2", "PG-01", "a.ts:2", "p", "f"]]), "",
            "## Approve",
            "Reply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.", "",
        ])
        self.assert_check(text, "sections")

    def test_a_gap_in_numbering_fails(self):
        self.assert_check(GOOD.replace("| 3 | PG-08", "| 5 | PG-08"), "numbering")

    def test_numbers_that_restart_in_each_table_fail(self):
        self.assert_check(GOOD.replace("| 2 | PG-03", "| 1 | PG-03"), "numbering")

    def test_a_duplicate_rule_id_fails_in_one_table_and_across_tables(self):
        self.assert_check(GOOD.replace("| 4 | PG-09", "| 4 | PG-08"), "unique")
        self.assert_check(GOOD.replace("| 2 | PG-03", "| 2 | PGJS-01"), "unique")

    def test_a_rule_cell_with_two_ids_fails(self):
        self.assert_check(GOOD.replace("| PG-03 |", "| PG-03, PG-04 |"), "unique")

    def test_a_where_cell_with_no_line_fails(self):
        self.assert_check(GOOD.replace("orders.ts:10 ", "orders.ts "), "where")
        self.assert_check(GOOD.replace("orders.ts:10 ", "orders.ts:0 "), "where")
        self.assert_check(GOOD.replace("orders.ts:30-32", "orders.ts:30-"), "where")

    def test_a_wrong_table_header_fails(self):
        self.assert_check(GOOD.replace("| # | Rule | Where | Problem | Fix |", "| # | Rule | Where | Fix |", 1), "tables")

    def test_a_row_with_a_missing_cell_fails(self):
        self.assert_check(GOOD.replace("| Use IN ${sql(ids)}. |", "|"), "rows")

    def test_a_new_line_inside_a_cell_fails(self):
        self.assert_check(GOOD.replace("Extra parentheses in IN.", "Extra\nparentheses in IN."), "rows")

    def test_an_escaped_pipe_inside_a_cell_is_one_cell(self):
        self.assert_pass(GOOD.replace("Extra parentheses in IN.", r"Extra \| parentheses in IN."))

    def test_a_wrong_approval_text_fails(self):
        self.assert_check(GOOD.replace("Reply with the findings to fix:", "Reply with:"), "approve")
        self.assert_check(EMPTY.replace("There is nothing to approve.", "Nothing."), "approve")

    def test_the_approval_text_for_findings_cannot_say_nothing_to_approve(self):
        self.assert_check(GOOD.split("## Approve")[0] + "## Approve\nThere is nothing to approve.\n", "approve")

    def test_an_approve_section_that_is_not_last_fails(self):
        approve = "## Approve\nReply with the findings to fix: `all`, `none`, a list such as `1,3,5`, or a range such as `1-12`.\n"
        text = GOOD.replace(approve, "")
        text = text.replace("## Critical", approve + "\n## Critical", 1)
        self.assert_check(text, "approve")

    def test_a_missing_approve_section_fails(self):
        self.assert_check(GOOD.split("## Approve")[0], "approve")

    def test_a_rewrite_with_no_label_fails(self):
        text = GOOD.replace(f"{LABEL} SELECT 1 FROM t. Run a database diff.", "Rewrite: SELECT 1 FROM t, database diff.")
        self.assert_check(text, "rewrite")

    def test_a_rewrite_with_no_database_diff_fails(self):
        self.assert_check(GOOD.replace("Run a database diff.", "Check it."), "rewrite")

    # Each label of `Rewrite proof` in optimize.md.
    LABELS = [
        "Rewrite (proven: database diff and repo tests):",
        "Rewrite (proven by the database diff only: no repo tests ran):",
        "Rewrite (partial proof by the database diff: order not checked, ties):",
        "Rewrite (partial proof by the database diff: order not checked, sort keys):",
        "Rewrite (unproven: no database):",
        "Rewrite (unproven: the database diff failed):",
        "Rewrite (unproven: write statement, no database diff):",
        "Rewrite (unproven: statement not complete, no database diff):",
    ]

    def test_each_label_of_the_module_passes_with_the_words_database_diff_after_the_sql(self):
        for label in self.LABELS:
            with self.subTest(label=label):
                self.assert_pass(GOOD.replace(f"{LABEL} SELECT 1 FROM t. Run a database diff.",
                                              f"{label} SELECT 1 FROM t. Run a database diff."))

    def test_a_label_that_holds_the_words_database_diff_passes_with_nothing_after_the_sql(self):
        for label in self.LABELS:
            if "database diff" in label:
                with self.subTest(label=label):
                    self.assert_pass(GOOD.replace(f"{LABEL} SELECT 1 FROM t. Run a database diff.", f"{label} SELECT 1 FROM t."))

    def test_the_label_with_no_database_diff_words_fails_with_nothing_after_the_sql(self):
        self.assert_check(GOOD.replace(f"{LABEL} SELECT 1 FROM t. Run a database diff.", f"{LABEL} SELECT 1 FROM t."), "rewrite")

    def test_a_label_that_is_not_one_of_the_module_labels_fails_even_with_database_diff(self):
        for label in ("Rewrite (proven):", "Rewrite (proven by the database diff):", "Rewrite (unproven: no database)",
                      "Rewrite (proven: database diff and repo tests)",
                      "Rewrite (unproven: write statement):", "Rewrite (partial proof: order not checked, ties):"):
            with self.subTest(label=label):
                self.assert_check(GOOD.replace(f"{LABEL} SELECT 1 FROM t. Run a database diff.",
                                               f"{label} SELECT 1 FROM t. Run a database diff."), "rewrite")

    def test_a_lower_case_rewrite_word_is_not_matched(self):
        self.assert_pass(GOOD.replace("List the columns.", "You can rewrite it as a list."))

    def test_the_capitalised_word_in_a_plain_fix_fails(self):
        self.assert_check(GOOD.replace("List the columns.", "Rewrite it as a list."), "rewrite")

    def test_a_missing_disabled_line_fails_when_disabled_is_given(self):
        self.assert_check(GOOD, "disabled", "--disabled", "PG-10")

    def test_a_disabled_line_that_differs_from_the_flag_fails(self):
        self.assert_check(WITH_DISABLED, "disabled", "--disabled", "PG-10")
        self.assert_check(WITH_DISABLED, "disabled", "--disabled", "PG-10", "PG-06", "PG-07")

    def test_a_disabled_id_in_a_table_fails(self):
        self.assert_check(WITH_DISABLED.replace("| PG-08 |", "| PG-10 |"), "disabled")
        self.assert_check(WITH_DISABLED.replace("| PG-08 |", "| PG-10 |"), "disabled", "--disabled", "PG-10", "PG-06")

    def test_a_disabled_id_named_twice_fails(self):
        self.assert_check(WITH_DISABLED.replace("PG-10, PG-06", "PG-10, PG-10"), "disabled")

    def test_a_disabled_line_with_a_bad_form_fails(self):
        self.assert_check(WITH_DISABLED.replace("Disabled rules: PG-10, PG-06.", "Disabled rules: PG-10 PG-06"), "disabled")

    def test_a_line_that_is_not_a_note_between_summary_and_tables_fails(self):
        self.assert_check(GOOD.replace("\n\n## Critical", "\nSome prose.\n\n## Critical", 1), "sections")

    def test_a_table_for_a_rule_found_in_an_unknown_heading_fails(self):
        self.assert_check(GOOD.replace("## Required", "## Other"), "sections")

    def test_an_unreadable_report_exits_2_with_no_verdict_line(self):
        code, out, err = run("grade_report.py", ["/no/such/report.md"])
        self.assertEqual((code, out), (2, []))
        self.assertTrue(err.strip())


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        self.evals = os.path.join(self.root, "evals")

    def case(self, name, expect=None, forbid=None, disabled=None, expect_json=True):
        if expect_json:
            data = {"expect": expect or [], "forbid": forbid or []}
            if disabled is not None:
                data["disabled"] = disabled
            write(os.path.join(self.evals, name, "expect.json"), json.dumps(data))
        else:
            os.makedirs(os.path.join(self.evals, name), exist_ok=True)

    def trace(self, name, message, calls=(), raw=None):
        path = os.path.join(self.root, "traces", name)
        if raw is None:
            lines = [assistant(*calls), json.dumps({"type": "result", "result": message})]
            raw = "\n".join(lines) + "\n"
        write(path, raw)
        return path

    def result(self, cases):
        path = os.path.join(self.root, "result.json")
        data = {"cases": [
            {"name": name, "arms": {"with": [{"tracePath": trace} for trace in traces]}}
            for name, traces in cases
        ]}
        write(path, json.dumps(data))
        return path

    def grade(self, result):
        return run("grade_eval_results.py", [result, "--evals", self.evals])

    def test_a_passing_run_prints_its_line_and_pass(self):
        self.case("opt-a", expect=["PGJS-01"], forbid=["PG-01"])
        path = self.trace("a1.jsonl", GOOD, [("Read", {"file_path": "orders.ts"})])
        code, out, _ = self.grade(self.result([("opt-a", [path])]))
        self.assertEqual((code, out), (0, ["opt-a#1: PASS", "PASS"]))

    def test_a_failing_run_prints_check_lines_and_fail(self):
        self.case("opt-a", expect=["PG-01"])
        ok = self.trace("a1.jsonl", GOOD, [("Read", {})])
        bad = self.trace("a2.jsonl", GOOD, [("Edit", {"file_path": "a.ts"})])
        code, out, _ = self.grade(self.result([("opt-a", [ok, bad])]))
        self.assertEqual(code, 1)
        self.assertEqual(out[-1], "FAIL")
        self.assertIn("opt-a#1: FAIL", out)
        self.assertIn("opt-a#2: FAIL", out)
        self.assertTrue(any(line.startswith("FAIL opt-a#1 expect:PG-01:") for line in out), out)
        self.assertTrue(any(line.startswith("FAIL opt-a#2 change:") for line in out), out)

    def test_a_report_with_a_bad_layout_fails_the_run(self):
        self.case("opt-a")
        path = self.trace("a1.jsonl", GOOD.replace("# sql optimize: orders.ts", "# report"), [("Read", {})])
        code, out, _ = self.grade(self.result([("opt-a", [path])]))
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL opt-a#1 title:") for line in out), out)

    def test_the_disabled_list_of_expect_json_is_passed_to_grader_i(self):
        self.case("opt-d", disabled=["PG-10", "PG-06"])
        path = self.trace("d1.jsonl", WITH_DISABLED, [("Read", {})])
        code, out, _ = self.grade(self.result([("opt-d", [path])]))
        self.assertEqual((code, out), (0, ["opt-d#1: PASS", "PASS"]))
        self.case("opt-d", disabled=["PG-10"])
        code, out, _ = self.grade(self.result([("opt-d", [path])]))
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL opt-d#1 disabled:") for line in out), out)

    def test_a_null_disabled_list_is_the_same_as_no_disabled_list(self):
        self.case("opt-a")
        write(os.path.join(self.evals, "opt-a", "expect.json"),
              json.dumps({"expect": [], "forbid": [], "disabled": None}))
        path = self.trace("a1.jsonl", GOOD, [("Read", {})])
        code, out, err = self.grade(self.result([("opt-a", [path])]))
        self.assertEqual((code, out), (0, ["opt-a#1: PASS", "PASS"]), err)

    def test_a_case_with_no_expect_json_is_skipped(self):
        self.case("opt-a")
        self.case("trigger-x", expect_json=False)
        path = self.trace("a1.jsonl", GOOD, [("Read", {})])
        other = self.trace("x1.jsonl", "not a report", [("Read", {})])
        code, out, _ = self.grade(self.result([("trigger-x", [other]), ("opt-a", [path])]))
        self.assertEqual((code, out), (0, ["opt-a#1: PASS", "PASS"]))

    def test_a_missing_trace_fails_the_run_and_names_keep_temp(self):
        self.case("opt-a")
        code, out, _ = self.grade(self.result([("opt-a", [os.path.join(self.root, "none.jsonl")])]))
        self.assertEqual(code, 1)
        self.assertTrue(any("--keep-temp" in line for line in out), out)
        self.assertEqual(out[-1], "FAIL")

    def test_a_run_with_no_trace_path_fails_with_keep_temp(self):
        self.case("opt-a")
        code, out, _ = self.grade(self.result([("opt-a", [""])]))
        self.assertEqual(code, 1)
        self.assertTrue(any("--keep-temp" in line for line in out), out)

    def test_a_trace_with_no_final_message_fails_the_run(self):
        self.case("opt-a")
        path = self.trace("a1.jsonl", None, raw=assistant(("Read", {})) + "\n")
        code, out, _ = self.grade(self.result([("opt-a", [path])]))
        self.assertEqual(code, 1)
        self.assertTrue(any("--keep-temp" in line for line in out), out)

    def test_a_corrupt_trace_fails_only_that_run_with_exit_1(self):
        self.case("opt-a")
        bad = self.trace("a1.jsonl", None, raw="{not json\n")
        ok = self.trace("a2.jsonl", GOOD, [("Read", {})])
        code, out, _ = self.grade(self.result([("opt-a", [bad, ok])]))
        self.assertEqual(code, 1)
        self.assertTrue(any(line.startswith("FAIL opt-a#1 trace:") and bad in line for line in out), out)
        self.assertIn("opt-a#1: FAIL", out)
        self.assertIn("opt-a#2: PASS", out)
        self.assertEqual(out[-1], "FAIL")

    def assert_exit_2(self, result):
        code, out, err = self.grade(result)
        self.assertEqual(code, 2)
        self.assertEqual(out, [])
        self.assertTrue(err.strip())

    def test_an_unreadable_result_exits_2(self):
        self.assert_exit_2(os.path.join(self.root, "missing.json"))
        bad = os.path.join(self.root, "bad.json")
        write(bad, "{not json")
        self.assert_exit_2(bad)
        shape = os.path.join(self.root, "shape.json")
        write(shape, json.dumps({"cases": "x"}))
        self.assert_exit_2(shape)

    def test_an_unusable_expect_json_exits_2(self):
        self.case("opt-a")
        path = self.trace("a1.jsonl", GOOD, [("Read", {})])
        result = self.result([("opt-a", [path])])
        for text in ("[]", "{not json", json.dumps({"expect": "PG-01", "forbid": []}),
                     json.dumps({"expect": [], "forbid": [], "disabled": "PG-10"})):
            with self.subTest(text=text):
                write(os.path.join(self.evals, "opt-a", "expect.json"), text)
                self.assert_exit_2(result)

    def test_no_graded_case_exits_2(self):
        self.case("trigger-x", expect_json=False)
        path = self.trace("x1.jsonl", GOOD, [("Read", {})])
        self.assert_exit_2(self.result([("trigger-x", [path])]))
        self.assert_exit_2(self.result([]))


if __name__ == "__main__":
    unittest.main()
