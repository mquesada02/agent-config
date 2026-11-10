import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(SKILL_DIR, "scripts", "plan_findings.py")
PLANS = os.path.join(HERE, "fixtures", "plans")


def run(args=(), stdin=None):
    return subprocess.run([sys.executable, "-I", SCRIPT, *args], input=stdin, capture_output=True, text=True)


def out(args=(), stdin=None):
    proc = run(args, stdin)
    return proc, json.loads(proc.stdout) if proc.stdout.strip() else None


def fixture(name):
    return os.path.join(PLANS, name + ".json")


def node(kind="Seq Scan", **fields):
    base = {"Node Type": kind, "Plan Rows": 1, "Actual Rows": 1, "Actual Loops": 1}
    base.update(fields)
    return base


def plan_of(root):
    return [{"Plan": root}]


def rules_of(result):
    return [f["rule"] for f in result["findings"]]


def findings_for(root, extra=()):
    """The rule ids for a root node that carries buffer counts, so PLAN-05 stays quiet."""
    root = dict(root)
    root.setdefault("Shared Hit Blocks", 2000)
    root.setdefault("Shared Read Blocks", 0)
    proc, result = out(["-"], json.dumps(plan_of(root)))
    return proc, result


class FixtureTest(unittest.TestCase):
    def test_each_rule_fixture_fires_only_its_rule(self):
        for number in range(1, 6):
            with self.subTest(rule=number):
                proc, result = out([fixture(f"plan-0{number}")])
                self.assertEqual(proc.returncode, 0)
                self.assertEqual(rules_of(result), [f"PLAN-0{number}"])
                self.assertEqual(result["notes"], [])
                self.assertTrue(result["analyze"])

    def test_the_clean_plan_has_no_finding_and_no_note(self):
        proc, result = out([fixture("clean")])
        self.assertEqual((proc.returncode, result["findings"], result["notes"], result["analyze"]),
                         (0, [], [], True))

    def test_a_postgresql_18_plan_with_fractional_rows_is_computed(self):
        proc, result = out([fixture("pg18-fractional")])
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(rules_of(result), ["PLAN-01"])
        measured = result["findings"][0]["measured"]
        self.assertAlmostEqual(measured["actual_rows"], 1500.5 * 3)
        self.assertAlmostEqual(measured["estimated_rows"], 100.25 * 3)
        self.assertAlmostEqual(measured["ratio"], 1500.5 / 100.25)

    def test_a_plan_without_analyze_gives_no_finding_and_the_note(self):
        proc, result = out([fixture("no-analyze")])
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(result["analyze"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["notes"]), 1)
        self.assertIn("no actual values", result["notes"][0])

    def test_the_finding_fields_and_the_measured_values(self):
        _, result = out([fixture("plan-02")])
        item = result["findings"][0]
        self.assertEqual(sorted(item), ["measured", "node", "path", "rule", "threshold"])
        self.assertEqual(item["node"], "Seq Scan on events")
        self.assertEqual(item["path"], ["Seq Scan"])
        self.assertEqual(item["measured"]["scanned_rows"], 30000)
        self.assertAlmostEqual(item["measured"]["removed_ratio"], 0.99)
        self.assertEqual(item["threshold"], {"min_scanned_rows": 10000, "min_removed_ratio": 0.9})


class Plan01Test(unittest.TestCase):
    def fires(self, actual, estimate, loops=1):
        _, result = findings_for(node(**{"Actual Rows": actual, "Plan Rows": estimate, "Actual Loops": loops}))
        return "PLAN-01" in rules_of(result)

    def test_the_floor_of_1000_actual_rows(self):
        self.assertFalse(self.fires(999, 1))
        self.assertTrue(self.fires(1000, 1))

    def test_the_ratio_of_10_in_both_directions(self):
        self.assertFalse(self.fires(1000, 101))
        self.assertTrue(self.fires(1000, 100))
        self.assertFalse(self.fires(1000, 9999))
        self.assertTrue(self.fires(1000, 10000))

    def test_the_floor_applies_to_an_overestimate_too(self):
        self.assertFalse(self.fires(5, 500))

    def test_loops_multiply_both_sides(self):
        self.assertTrue(self.fires(500, 5, loops=2))
        self.assertFalse(self.fires(300, 5, loops=2))

    def test_an_estimate_of_zero_fires_with_a_null_ratio(self):
        _, result = findings_for(node(**{"Actual Rows": 2000, "Plan Rows": 0}))
        self.assertEqual(result["findings"][0]["measured"]["ratio"], None)


class Plan02Test(unittest.TestCase):
    def fires(self, rows, removed, loops=1, kind="Seq Scan"):
        root = node(kind, **{"Actual Rows": rows, "Plan Rows": rows, "Rows Removed by Filter": removed,
                             "Actual Loops": loops})
        _, result = findings_for(root)
        return "PLAN-02" in rules_of(result)

    def test_the_scanned_rows_floor(self):
        self.assertFalse(self.fires(9, 9990))
        self.assertTrue(self.fires(10, 9990))

    def test_the_removed_ratio_fires_at_090(self):
        self.assertFalse(self.fires(1100, 8900))
        self.assertTrue(self.fires(1000, 9000))

    def test_loops_multiply_the_scanned_rows_only(self):
        self.assertTrue(self.fires(5, 495, loops=20))
        self.assertFalse(self.fires(5, 495, loops=19))

    def test_only_a_seq_scan_counts(self):
        self.assertFalse(self.fires(10, 99990, kind="Index Scan"))

    def test_a_missing_removed_count_does_not_fire(self):
        _, result = findings_for(node(**{"Actual Rows": 1, "Plan Rows": 1}))
        self.assertNotIn("PLAN-02", rules_of(result))


class Plan03Test(unittest.TestCase):
    def measured(self, **fields):
        _, result = findings_for(node("Sort", **fields))
        return [f["measured"] for f in result["findings"] if f["rule"] == "PLAN-03"]

    def test_a_sort_method(self):
        self.assertEqual(self.measured(**{"Sort Method": "quicksort"}), [])
        self.assertEqual(self.measured(**{"Sort Method": "external merge"}),
                         [{"sort_method": "external merge"}])
        self.assertEqual(len(self.measured(**{"Sort Method": "External sort"})), 1)

    def test_hash_batches(self):
        self.assertEqual(self.measured(**{"Hash Batches": 1}), [])
        self.assertEqual(self.measured(**{"Hash Batches": 2}), [{"hash_batches": 2}])

    def test_temp_blocks_that_the_node_adds(self):
        self.assertEqual(self.measured(**{"Temp Written Blocks": 0}), [])
        self.assertEqual(self.measured(**{"Temp Written Blocks": 7}), [{"temp_written_blocks": 7}])

    def test_blocks_that_a_child_already_holds_give_no_finding_at_the_parent(self):
        child = node("Hash", **{"Temp Written Blocks": 40, "Hash Batches": 4})
        parent = node("Hash Join", **{"Temp Written Blocks": 40, "Plans": [child]})
        _, result = findings_for(parent)
        self.assertEqual([(f["rule"], f["node"]) for f in result["findings"]], [("PLAN-03", "Hash")])

    def test_blocks_above_the_children_sum_are_reported_at_the_parent(self):
        child = node("Hash", **{"Temp Written Blocks": 40})
        parent = node("Hash Join", **{"Temp Written Blocks": 55, "Plans": [child]})
        _, result = findings_for(parent)
        by_node = {f["node"]: f["measured"] for f in result["findings"]}
        self.assertEqual(by_node["Hash Join"], {"temp_written_blocks": 15})

    def test_one_finding_for_a_node_with_two_signals(self):
        measured = self.measured(**{"Sort Method": "external merge", "Temp Written Blocks": 9})
        self.assertEqual(measured, [{"sort_method": "external merge", "temp_written_blocks": 9}])

    def test_the_threshold_object(self):
        _, result = findings_for(node("Sort", **{"Hash Batches": 2}))
        self.assertEqual(result["findings"][0]["threshold"], {"hash_batches": 1, "temp_written_blocks": 0})


class Plan04Test(unittest.TestCase):
    def fires(self, inner_loops, relationship="Inner", order=0):
        outer = node("Seq Scan", **{"Parent Relationship": "Outer"})
        inner = node("Index Scan", **{"Actual Loops": inner_loops})
        if relationship:
            inner["Parent Relationship"] = relationship
        kids = [outer, inner] if order == 0 else [inner, outer]
        _, result = findings_for(node("Nested Loop", Plans=kids))
        return "PLAN-04" in rules_of(result)

    def test_the_inner_loops_floor(self):
        self.assertFalse(self.fires(999))
        self.assertTrue(self.fires(1000))

    def test_the_inner_child_by_parent_relationship(self):
        self.assertTrue(self.fires(1000, order=1))

    def test_the_second_child_when_no_child_names_a_relationship(self):
        outer = node("Seq Scan", **{"Actual Loops": 5000})
        inner = node("Index Scan", **{"Actual Loops": 5})
        _, result = findings_for(node("Nested Loop", Plans=[outer, inner]))
        self.assertNotIn("PLAN-04", rules_of(result))
        outer["Actual Loops"], inner["Actual Loops"] = 1, 5000
        _, result = findings_for(node("Nested Loop", Plans=[outer, inner]))
        self.assertIn("PLAN-04", rules_of(result))

    def test_only_a_nested_loop_counts(self):
        outer = node("Seq Scan")
        inner = node("Index Scan", **{"Actual Loops": 5000, "Parent Relationship": "Inner"})
        _, result = findings_for(node("Hash Join", Plans=[outer, inner]))
        self.assertNotIn("PLAN-04", rules_of(result))

    def test_the_measured_values(self):
        _, result = out([fixture("plan-04")])
        item = result["findings"][0]
        self.assertEqual(item["measured"], {"inner_loops": 2000, "inner_node": "Index Scan on orders"})
        self.assertEqual(item["threshold"], {"min_inner_loops": 1000})


class Plan05Test(unittest.TestCase):
    def result(self, hits, reads):
        root = node(**{"Shared Hit Blocks": hits, "Shared Read Blocks": reads})
        return out(["-"], json.dumps(plan_of(root)))[1]

    def test_the_read_blocks_floor(self):
        self.assertEqual(rules_of(self.result(0, 999)), [])
        self.assertEqual(rules_of(self.result(0, 1000)), ["PLAN-05"])

    def test_the_hit_ratio_fires_below_090(self):
        self.assertEqual(rules_of(self.result(9000, 1000)), [])
        self.assertEqual(rules_of(self.result(8999, 1000)), ["PLAN-05"])

    def test_the_finding_is_about_the_root(self):
        item = self.result(100, 1500)["findings"][0]
        self.assertEqual((item["node"], item["path"]), ("Seq Scan", ["Seq Scan"]))
        self.assertEqual(item["measured"]["shared_read_blocks"], 1500)
        self.assertEqual(item["threshold"], {"min_shared_read_blocks": 1000, "max_hit_ratio": 0.9})

    def test_no_buffer_counts_gives_a_note(self):
        _, result = out(["-"], json.dumps(plan_of(node())))
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["notes"]), 1)
        self.assertIn("no buffer counts", result["notes"][0])

    def test_a_root_that_never_ran_still_counts_its_buffers(self):
        root = node(**{"Actual Loops": 0, "Shared Hit Blocks": 0, "Shared Read Blocks": 2000})
        self.assertEqual(rules_of(out(["-"], json.dumps(plan_of(root)))[1]), ["PLAN-05"])


class WalkTest(unittest.TestCase):
    def test_a_finding_in_a_nested_child_has_its_path(self):
        deep = node("Seq Scan", Relation_Name="x", **{"Actual Rows": 5000, "Plan Rows": 10})
        mid = node("Sort", Plans=[deep])
        root = node("Limit", Plans=[mid])
        _, result = findings_for(root)
        self.assertEqual(result["findings"][0]["path"], ["Limit", "Sort", "Seq Scan"])

    def test_a_finding_in_a_subplan_is_found(self):
        sub = node("Seq Scan", **{"Actual Rows": 5000, "Plan Rows": 10, "Parent Relationship": "SubPlan"})
        _, result = findings_for(node("Result", Plans=[sub]))
        self.assertEqual(rules_of(result), ["PLAN-01"])

    def test_a_node_that_never_ran_is_skipped_but_its_children_are_visited(self):
        child = node("Seq Scan", **{"Actual Rows": 5000, "Plan Rows": 10})
        parent = node("Sort", **{"Actual Loops": 0, "Actual Rows": 5000, "Plan Rows": 10, "Plans": [child]})
        _, result = findings_for(parent)
        self.assertEqual([f["path"] for f in result["findings"]], [["Sort", "Seq Scan"]])

    def test_findings_are_in_plan_order_then_rule_order(self):
        first = node("Seq Scan", Relation_Name="a", **{"Actual Rows": 5000, "Plan Rows": 10})
        second = node("Sort", **{"Hash Batches": 3})
        root = node("Append", Plans=[first, second])
        _, result = findings_for(root)
        self.assertEqual([(f["rule"], f["path"][-1]) for f in result["findings"]],
                         [("PLAN-01", "Seq Scan"), ("PLAN-03", "Sort")])

    def test_a_key_that_is_not_a_number_counts_as_missing(self):
        _, result = findings_for(node(**{"Actual Rows": "5000", "Plan Rows": 10}))
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["analyze"])


class InputTest(unittest.TestCase):
    def test_a_pg_run_object_gives_the_version_and_the_same_findings_as_a_bare_list(self):
        with open(fixture("plan-01"), encoding="utf-8") as handle:
            plan = json.load(handle)
        wrapped = {"ok": True, "action": "explain", "ran": "analyze", "server_version_num": 180000, "plan": plan}
        _, from_object = out(["-"], json.dumps(wrapped))
        _, from_list = out(["-", "--server-version-num", "170002"], json.dumps(plan))
        self.assertEqual(from_object["server_version_num"], 180000)
        self.assertEqual(from_list["server_version_num"], 170002)
        self.assertEqual(from_object["findings"], from_list["findings"])

    def test_a_bare_list_without_a_version_gives_null(self):
        _, result = out([fixture("clean")])
        self.assertIsNone(result["server_version_num"])

    def test_a_pg_run_object_without_a_numeric_version_gives_null(self):
        with open(fixture("clean"), encoding="utf-8") as handle:
            plan = json.load(handle)
        _, result = out(["-"], json.dumps({"ok": True, "server_version_num": "18", "plan": plan}))
        self.assertIsNone(result["server_version_num"])

    def test_the_version_argument_does_not_fill_the_version_of_a_pg_run_object(self):
        with open(fixture("clean"), encoding="utf-8") as handle:
            plan = json.load(handle)
        _, result = out(["-", "--server-version-num", "5"], json.dumps({"ok": True, "server_version_num": "x", "plan": plan}))
        self.assertIsNone(result["server_version_num"])

    def test_stdin_and_a_file_give_the_same_result(self):
        with open(fixture("plan-03"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(out([fixture("plan-03")])[1], out(["-"], text)[1])
        self.assertEqual(out([], text)[1], out(["-"], text)[1])

    def test_the_plan_is_echoed_unchanged(self):
        with open(fixture("plan-05"), encoding="utf-8") as handle:
            plan = json.load(handle)
        self.assertEqual(out([fixture("plan-05")])[1]["plan"], plan)


class PassThroughTest(unittest.TestCase):
    def test_a_failed_plan_call_is_passed_on_with_its_object(self):
        failed = {"ok": False, "error": "refused", "reason": "write_statement", "service": "app-pg13"}
        proc, result = out(["-"], json.dumps(failed))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(result, {"ok": False, "error": "pg_run_failed", "source_error": "refused", "source": failed})

    def test_a_connection_failure_keeps_its_redacted_message(self):
        failed = {"ok": False, "error": "connection_failed", "message": "connection to server at app-x failed"}
        _, result = out(["-"], json.dumps(failed))
        self.assertEqual(result["source"]["message"], failed["message"])
        self.assertEqual(result["source_error"], "connection_failed")

    def test_a_piped_pg_run_output_is_read(self):
        pg_run = subprocess.run([sys.executable, "-c",
                                 "import json; print(json.dumps({'ok': True, 'server_version_num': 130000, "
                                 "'plan': json.load(open(%r))}))" % fixture("plan-02")],
                                capture_output=True, text=True, check=True)
        _, result = out(["-"], pg_run.stdout)
        self.assertEqual(rules_of(result), ["PLAN-02"])
        self.assertEqual(result["server_version_num"], 130000)


class ContractTest(unittest.TestCase):
    def test_the_output_is_one_line_that_starts_with_ok_first(self):
        for name, prefix in (("plan-01", '{"ok": true'), ("no-analyze", '{"ok": true')):
            proc = run([fixture(name)])
            self.assertEqual(proc.stdout.count("\n"), 1)
            self.assertTrue(proc.stdout.startswith(prefix), proc.stdout[:30])
        proc = run(["-"], "not json")
        self.assertTrue(proc.stdout.startswith('{"ok": false'))

    def test_a_finding_has_no_severity(self):
        _, result = out([fixture("plan-03")])
        self.assertNotIn("severity", result["findings"][0])

    def test_text_that_is_not_json_gives_bad_input(self):
        proc, result = out(["-"], "this is not json")
        self.assertEqual((proc.returncode, result["error"]), (1, "bad_input"))
        self.assertIn("message", result)

    def test_json_with_no_plan_gives_bad_input(self):
        for document in ('{"x": 1}', "[]", '[{"Planning": {}}]', '"text"', "[1]", '{"ok": true, "plan": []}'):
            with self.subTest(document=document):
                proc, result = out(["-"], document)
                self.assertEqual((proc.returncode, result["error"]), (1, "bad_input"))

    def test_a_non_finite_number_gives_bad_input_and_the_output_is_strict_json(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                document = '[{"Plan": {"Node Type": "Seq Scan", "Plan Rows": 100, "Actual Rows": %s, "Actual Loops": 1}}]'
                proc = run(["-"], document % constant)
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                result = json.loads(proc.stdout, parse_constant=lambda name: self.fail(f"bare {name} in the output"))
                self.assertEqual((result["ok"], result["error"]), (False, "bad_input"))

    def test_a_number_that_is_or_becomes_not_finite_gives_bad_input_and_the_output_is_strict_json(self):
        root = '{"Node Type": "Seq Scan", "Plan Rows": %s, "Actual Rows": %s, "Actual Loops": %s}'
        for label, fields in (("overflow", ("5", "1e999", "1")), ("both overflow", ("1e999", "1e999", "1")),
                              ("product overflows", ("5", "1e308", "1e308")), ("huge integer", ("1", "1" + "0" * 400, "1"))):
            with self.subTest(case=label):
                proc = run(["-"], "[{\"Plan\": " + root % fields + "}]")
                self.assertEqual((proc.returncode, proc.stderr), (1, ""), proc.stderr[-300:])
                result = json.loads(proc.stdout, parse_constant=lambda name: self.fail(f"bare {name} in the output"))
                self.assertEqual((result["ok"], result["error"]), (False, "bad_input"))

    def test_a_plan_file_with_bytes_that_are_not_utf_8_gives_bad_input_like_stdin(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "plan.json")
            with open(path, "wb") as handle:
                handle.write(b"\xff\xfe[")
            for args, stdin in (([path], None), (["-"], "��[")):
                with self.subTest(args=args):
                    proc, result = out(args, stdin)
                    self.assertEqual((proc.returncode, proc.stderr), (1, ""), proc.stderr[-300:])
                    self.assertEqual((result["ok"], result["error"]), (False, "bad_input"))

    def test_a_plan_nested_too_deep_gives_bad_input_and_no_traceback(self):
        for depth in (1000, 5000):
            with self.subTest(depth=depth):
                text = '{"Node Type": "Result", "Actual Rows": 1, "Actual Loops": 1, "Plans": [' * depth
                text = '[{"Plan": ' + text + "{}" + "]}" * depth + "}]"
                proc, result = out(["-"], text)
                self.assertEqual((proc.returncode, proc.stderr), (1, ""), proc.stderr[-300:])
                self.assertEqual((result["ok"], result["error"]), (False, "bad_input"))

    def test_empty_input_gives_bad_input(self):
        proc, result = out(["-"], "")
        self.assertEqual((proc.returncode, result["error"]), (1, "bad_input"))

    def test_a_usage_error_exits_2_with_one_line_on_stderr(self):
        for args in (["--server-version-num", "abc", "-"], ["--unknown"], ["/nonexistent/plan.json"]):
            with self.subTest(args=args):
                proc = run(args, "")
                self.assertEqual((proc.returncode, proc.stdout), (2, ""))
                self.assertEqual(len(proc.stderr.strip().splitlines()) >= 1, True)

    def test_it_writes_no_file_and_opens_no_connection(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("socket", "subprocess", "urllib", "psql", "open(path, \"w", "write("):
            self.assertNotIn(needle, text)
        imported = {line.split()[1].split(".")[0] for line in text.splitlines() if line.startswith("import ")}
        self.assertTrue(imported <= {"argparse", "json", "math", "sys"}, imported)
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run([sys.executable, "-I", SCRIPT, fixture("plan-01")], cwd=folder,
                                  capture_output=True, text=True, env={})
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(os.listdir(folder), [])


if __name__ == "__main__":
    unittest.main()
