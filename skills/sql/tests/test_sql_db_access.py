import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
DB_ACCESS = os.path.join(SKILL_DIR, "db-access.md")
OPTIMIZE = os.path.join(SKILL_DIR, "optimize.md")
ROUTER = os.path.join(SKILL_DIR, "SKILL.md")

# The stub sections that db-access.md keeps: heading -> the ticket that fills it.
STUB_SECTIONS = {"Write mode (stub)": "#396", "Diff (stub)": "#397"}
SECTIONS = (
    "Rules", "Allowlist", "pg_run", "Read-only path", "Statements that EXPLAIN cannot take",
    "No full result", "Timeouts and versions", "Residual risk", "Facts",
)
ERROR_KINDS = ("not_allowed", "refused", "connection_failed", "statement_failed", "psql_failed", "bad_output")
GUARD_REASONS = (
    "empty", "unterminated", "multiple_statements", "write_statement", "not_select", "data_modifying",
    "forbidden_function", "unicode_identifier",
)
ALLOWLIST_REASONS = ("no_repo", "missing_file", "unreadable_file", "malformed_file", "no_entry", "service_not_listed")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}$", text, re.M)
    assert match, f"no section {heading}"
    return text[match.end():].split("\n## ", 1)[0]


def lines_with(text, code):
    return [line for line in text.splitlines() if f"`{code}`" in line]


class DbAccessModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(DB_ACCESS)
        cls.headings = re.findall(r"(?m)^## (.+)$", cls.text)

    def test_the_facts_section_is_not_a_stub_and_describes_the_action(self):
        facts = section(self.text, "Facts")
        self.assertNotRegex(facts, r"(?i)\bstub\b")
        self.assertNotIn("#400", facts)
        self.assertIn("pg_run.py facts --repo <repo root> --service <name> --names", facts)
        for needle in ("table.column", "schema.table.column", "nullable", "type", "missing", "null"):
            with self.subTest(needle=needle):
                self.assertIn(f"`{needle}`", facts)
        self.assertRegex(facts, r"(?i)catalog metadata only")
        self.assertRegex(facts, r"(?i)view")
        self.assertRegex(facts, r"(?i)non-ASCII|printable ASCII")
        self.assertRegex(facts, r"(?i)no `psql` call|never sent")
        for error in (kind for kind in ERROR_KINDS if kind != "refused"):
            self.assertIn(error, facts)
        self.assertNotIn("refused", facts)

    def test_the_intro_and_the_no_full_result_section_name_facts(self):
        self.assertIn("facts", self.text.split("\n## ", 1)[0])
        self.assertRegex(section(self.text, "No full result"), r"(?i)`pg_run facts` returns catalog metadata only")
        self.assertIn("no write path", self.text)

    def test_it_is_not_a_stub_outside_its_stub_sections(self):
        body = self.text
        for heading in STUB_SECTIONS:
            body = body.replace(section(self.text, heading), "")
        self.assertNotRegex(body.replace("(stub)", ""), r"(?i)\bstub\b")
        self.assertNotRegex(self.text.split("\n## ", 1)[0], r"(?i)\bstub\b")

    def test_it_has_each_required_section_and_one_stub_for_each_later_ticket(self):
        for heading in SECTIONS:
            with self.subTest(heading=heading):
                self.assertIn(heading, self.headings)
        for heading, ticket in STUB_SECTIONS.items():
            with self.subTest(heading=heading):
                self.assertIn(heading, self.headings)
                self.assertIn(ticket, section(self.text, heading))

    def test_the_rules_say_what_claude_never_does(self):
        body = section(self.text, "Rules")
        for fact in ("Never run `psql`", "~/.pgpass", "PG service file", "allowlist file", "environment variables"):
            with self.subTest(fact=fact):
                self.assertIn(fact, body)
        self.assertIn("pg_run.py", body)

    def test_the_allowlist_section_holds_the_file_the_key_and_the_reader_command(self):
        body = section(self.text, "Allowlist")
        for fact in (
            "allowlist.toml", "XDG_CONFIG_HOME", "origin", "git common dir", "services", "timeouts",
            "allowlist.py <repo root>", "--check-services", "access", "reason",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, body)
        for reason in ALLOWLIST_REASONS[:-1]:
            with self.subTest(reason=reason):
                self.assertIn(f"`{reason}`", body)

    def test_the_pg_run_section_holds_the_command_the_fields_and_each_error_kind(self):
        body = section(self.text, "pg_run")
        self.assertIn("pg_run.py explain --repo <repo root> --service <name> --mode select", body)
        for field in ("--statement", "stdin", "ok", "plan", "server_version_num", "timeouts", "warnings", "message"):
            with self.subTest(field=field):
                self.assertIn(field, body)
        for kind in ERROR_KINDS:
            with self.subTest(kind=kind):
                self.assertTrue(any("Claude" in line for line in lines_with(body, kind)), kind)

    def test_each_guard_reason_and_each_allowlist_reason_says_what_claude_does(self):
        for code in GUARD_REASONS + ("service_not_listed",):
            with self.subTest(code=code):
                found = [line for text in (self.text,) for line in lines_with(text, code)]
                self.assertTrue(any("Claude" in line for line in found), code)

    def test_a_static_review_only_statement_gets_no_pg_run_call(self):
        body = section(self.text, "Statements that EXPLAIN cannot take")
        self.assertIn("static_review_only", body)
        self.assertRegex(body, r"(?i)no `?pg_run`? call|no connection")

    def test_the_read_only_path_names_what_select_mode_sets_and_refuses(self):
        body = section(self.text, "Read-only path")
        for fact in (
            "default_transaction_read_only", "BEGIN READ ONLY", "standard_conforming_strings", "set_config",
            "VACUUM", "LISTEN", "NOTIFY", "advisory", "options=", "LC_ALL=C",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, body)

    def test_the_no_full_result_rule(self):
        body = section(self.text, "No full result")
        self.assertRegex(body, r"(?i)plan only")
        self.assertRegex(body, r"(?i)never.*(result rows|rows)")

    def test_the_timeouts_and_version_table(self):
        body = section(self.text, "Timeouts and versions")
        for fact in (
            "statement_timeout", "30s", "lock_timeout", "2s", "idle_in_transaction_session_timeout", "10s",
            "transaction_timeout", "60s", "170000", "180000", "BUFFERS", "PGCONNECT_TIMEOUT",
        ):
            with self.subTest(fact=fact):
                self.assertIn(fact, body)

    def test_the_residual_risk_names_the_role(self):
        body = section(self.text, "Residual risk")
        self.assertRegex(body, r"(?i)write rights|write privilege")
        self.assertRegex(body, r"(?i)role")
        self.assertRegex(body, r"(?i)guard")


class OptimizeDatabasePathTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(OPTIMIZE)
        cls.path = section(cls.text, "Database path")

    def test_the_stub_heading_is_gone_and_the_section_exists(self):
        self.assertNotIn("## Database path (stub)", self.text)
        self.assertIn("## Database path\n", self.text)

    def test_the_path_calls_pg_run_explain_and_names_its_gates(self):
        self.assertIn("pg_run.py explain", self.path)
        self.assertIn("allowlist.py", self.path)
        self.assertNotIn("--check-services", self.path.replace("does not run `--check-services`", ""))
        self.assertRegex(self.path, r"(?i)rules file")
        self.assertRegex(self.path, r"(?i)`found` is false|no rules file")
        self.assertRegex(self.path, r"(?i)user named|ask which")
        self.assertRegex(self.path, r"\$\{\.\.\.\}")
        self.assertRegex(self.path, r"\$n")

    def test_a_failed_call_is_one_note_line_and_no_plan_row_is_written(self):
        self.assertRegex(self.path, r"`Note:")
        self.assertRegex(self.path, r"(?i)failed")
        self.assertRegex(self.path, r"(?i)no `PLAN-\*` row")

    def test_the_path_has_the_catalog_facts_step_with_its_call_gates_and_fallback(self):
        facts = next(p for p in re.split(r"\n\n", self.path) if "Catalog facts" in p)
        self.assertNotRegex(self.path, r"(?i)\bstub\b")
        self.assertNotIn("#400", self.path)
        self.assertIn("pg_run.py facts", self.path)
        self.assertRegex(facts, r"PG-02")
        self.assertRegex(facts, r"PGJS-02")
        self.assertRegex(facts, r"(?i)one `?pg_run\.py facts`? call")
        self.assertRegex(self.path, r"(?i)no `facts` call")
        self.assertRegex(self.path, r"(?i)repo-fact rule")
        self.assertIn("Note: the facts call failed (<error>), so the rules use only the facts that the repo shows.", self.path)
        self.assertRegex(self.path, r"(?i)exactly one table")
        self.assertRegex(self.path, r"(?i)INSERT INTO")

    def test_the_steps_list_points_to_the_section_before_the_report_step(self):
        steps = [line for line in section(self.text, "Steps").splitlines() if re.match(r"\d+\. ", line)]
        index = next(i for i, line in enumerate(steps) if "Database path" in line)
        self.assertLess(index, next(i for i, line in enumerate(steps) if "Write the report" in line))

    def test_pg_run_and_psql_appear_nowhere_else(self):
        self.assertNotRegex(self.text, r"\bpsql\b")
        outside = self.text.replace(self.path, "")
        self.assertNotRegex(outside, r"\bpg_run\b")

    def test_the_first_paragraph_names_both_paths(self):
        first = self.text.split("\n## ", 1)[0]
        self.assertRegex(first, r"(?i)never connects")
        self.assertIn("db-access.md", first)
        self.assertIn("## Database path", self.text)
        self.assertIn("Database path", first)

    def test_the_other_stubs_are_kept(self):
        for ticket in ("#395", "#396", "#397"):
            with self.subTest(ticket=ticket):
                self.assertIn(ticket, self.text)


class RouterLineTest(unittest.TestCase):
    def test_optimize_loads_db_access_only_at_the_database_path(self):
        line = next(l for l in read(ROUTER).splitlines() if l.startswith("- `/sql optimize`"))
        self.assertIn("optimize.md", line)
        self.assertIn("db-access.md", line)
        self.assertIn("Database path", line)
        self.assertRegex(line, r"(?i)only when")


if __name__ == "__main__":
    unittest.main()
