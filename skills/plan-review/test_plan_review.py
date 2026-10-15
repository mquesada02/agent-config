import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CLAUDE_MD = os.path.join(REPO, "CLAUDE.md")
SKILL = os.path.join(HERE, "SKILL.md")
SPEC_AXES = os.path.join(HERE, "spec-axes.md")
TICKETS_AXES = os.path.join(HERE, "tickets-axes.md")
STEP_PREFIX = re.compile(r"^\d+(\.\d+)?\. ")
LOOP_MARKER = "plan-review loop:"
CODE_REVIEW = "/mattpocock-skills:code-review"


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def axis_headings(path):
    return re.findall(r"^## (.+)$", read(path), re.M)


def skill_section(text, heading):
    """Text of a `## <heading>` section of SKILL.md."""
    match = re.search(rf"^## {re.escape(heading)}$", text, re.M)
    assert match, f"SKILL.md has no section {heading}"
    return text[match.end():].split("\n## ", 1)[0]


def input_list(inputs, case):
    """The paragraph of the Inputs section that starts with `case` (a mode and case word in backticks)."""
    blocks = [block for block in inputs.split("\n\n") if block.startswith(case)]
    assert len(blocks) == 1, f"expected one input list for {case}, got {len(blocks)}"
    return blocks[0]


def section(text, number):
    """Text of the section whose heading starts with `## <number>.`, up to the next `## ` heading."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(f"## {number}.")), None)
    assert start is not None, f"CLAUDE.md has no section {number}"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def sentence_with(lines, *markers):
    """The one sentence of the joined lines that contains every marker, lowercased."""
    sentences = [
        s.lower() for s in re.split(r"(?<=[.])\s+", " ".join(lines))
        if all(m in s.lower() for m in markers)
    ]
    assert len(sentences) == 1, f"expected one sentence with {markers}, got {len(sentences)}"
    return sentences[0]


def step(lines, prefix):
    """Lines of a section 7 step: from its number prefix to the next line that starts a step."""
    start = next((i for i, line in enumerate(lines) if line.startswith(f"{prefix}. ")), None)
    assert start is not None, f"section 7 has no step {prefix}"
    end = next((i for i in range(start + 1, len(lines)) if STEP_PREFIX.match(lines[i])), len(lines))
    return "\n".join(lines[start:end])


class SkillFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = read(SKILL)

    def test_frontmatter_names_plan_review(self):
        text = self.skill
        match = re.match(r"---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(match, "SKILL.md has no frontmatter")
        fields = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
        self.assertEqual(fields.get("name"), "plan-review")
        description = fields.get("description", "").lower()
        self.assertIn("spec", description)
        self.assertIn("ticket breakdown", description)

    def test_inputs_name_the_sources_per_case(self):
        inputs = skill_section(self.skill, "Inputs").lower()
        cases = {
            "`spec general`": ("the spec", "the map", "decision tickets", "request", "quote"),
            "`spec ticket`": ("the spec", "the ticket", "the map"),
            "`tickets`": ("general spec", "ticket issues"),
        }
        for case, words in cases.items():
            text = input_list(inputs, case)
            for word in words:
                with self.subTest(case=case, word=word):
                    self.assertIn(word, text)

    def test_process_stops_and_asks(self):
        text = skill_section(self.skill, "Process").lower()
        self.assertIn("stop and ask", text)
        for phrase in ("input is missing", "mode is unknown", "case is missing or unknown", "a case word is given"):
            self.assertIn(phrase, text)

    def test_process_requires_sonnet_and_report_shape(self):
        text = skill_section(self.skill, "Process").lower()
        self.assertIn("set a sonnet model in each agent call", text)
        for word in ("blocking", "minor", "counts", "most severe", "no findings"):
            self.assertIn(word, text)
        for phrase in ("fidelity or coverage", "fidelity, clarity, codebase fit", "coverage, slicing, edges"):
            self.assertIn(phrase, text)

    def test_tickets_mode_is_built(self):
        self.assertNotIn("not built yet", self.skill.lower())
        body = self.skill.split("\n---\n", 1)[1]
        self.assertIn("/plan-review tickets", body.split("\n## ", 1)[0])

    def test_source_and_severity_cover_tickets_mode(self):
        source = skill_section(self.skill, "Source for each axis")
        for word in ("Coverage", "Slicing", "Edges"):
            self.assertIn(word, source)
        self.assertIn("label wins", skill_section(self.skill, "Severity").lower())
        axes = read(TICKETS_AXES).lower()
        for phrase in (
            "(missing, blocking)", "(extra, minor)", "horizontal slice is blocking",
            "too big for one worker is blocking", "without them is blocking",
            "in one ticket is blocking", "missing edge is blocking", "a cycle is blocking",
            "such a pair is blocking",
        ):
            self.assertIn(phrase, axes)

    def test_spec_axes_reference_names_three_axes(self):
        self.assertEqual(axis_headings(SPEC_AXES), ["Fidelity", "Clarity", "Codebase fit"])

    def test_tickets_axes_reference_names_three_axes(self):
        self.assertEqual(axis_headings(TICKETS_AXES), ["Coverage", "Slicing", "Edges"])


class ClaudeMdWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(CLAUDE_MD)
        cls.section7 = section(cls.text, 7)
        cls.step3 = step(cls.section7, "3")
        cls.step41 = step(cls.section7, "4.1")
        cls.step53 = step(cls.section7, "5.3")
        cls.loop_block = cls.step3.lower().partition(LOOP_MARKER)[2]

    def test_steps_do_not_name_code_review(self):
        for text in (self.step3, self.step41, self.step53):
            self.assertNotIn(CODE_REVIEW, text)

    def test_step_41_names_tickets_mode_and_who_applies_fixes(self):
        text = self.step41.lower()
        self.assertIn("/plan-review tickets", text)
        for word in (
            "same plan-review loop as in step 3", "main section 7 session",
            "before any dispatch", "ticket issues", "blocking edges", "general spec",
        ):
            self.assertIn(word, text)

    def test_step_41_sits_between_step_4_and_step_5(self):
        index = {}
        for prefix in ("4. ", "4.1. ", "5. "):
            hits = [i for i, line in enumerate(self.section7) if line.startswith(prefix)]
            self.assertEqual(len(hits), 1, prefix)
            index[prefix] = hits[0]
        self.assertLess(index["4. "], index["4.1. "])
        self.assertLess(index["4.1. "], index["5. "])

    def test_steps_name_the_case_and_who_applies_fixes(self):
        self.assertIn("/plan-review spec general", self.step3)
        self.assertIn("/plan-review spec ticket", self.step53)
        self.assertIn("main section 7 session", self.step3.lower())
        self.assertIn("before any dispatch", self.step3.lower())
        self.assertIn("spec issue body", self.step3.lower())
        self.assertIn("the worker applies every fix", self.step53.lower())
        self.assertIn("spec issue body", self.step53.lower())

    def test_all_steps_use_the_loop(self):
        for text in (self.step3, self.step41, self.step53):
            self.assertIn("plan-review loop", text.lower())

    def test_loop_block_is_stated_once_in_step_3(self):
        markers = [line for line in self.section7 if line.lower().startswith(LOOP_MARKER)]
        self.assertEqual(len(markers), 1)
        block = self.loop_block
        for word in (
            "correctness phase", "final phase", "1 round has no new blocking finding", "findings ledger",
            "apply the recorded minor", "cap: 5 rounds", "has no `/simplify`", "differs from section 6",
        ):
            self.assertIn(word, block)
        self.assertEqual(re.findall(r"^\(([a-d])\) ", block, re.M), ["a", "b", "c", "d"])

    def loop_step(self, letter):
        match = re.search(rf"^\({letter}\) (.*)$", self.loop_block, re.M)
        assert match, f"plan-review loop has no step ({letter})"
        return match.group(1)

    def test_final_phase_counts_only_blocking(self):
        text = self.loop_step("c")
        for word in (
            "only blocking findings fail a round",
            "done after 1 round with no blocking finding",
            "cap: 3 rounds",
            "a new minor finding in (c) is recorded and listed for the user, not applied",
        ):
            self.assertIn(word, text)

    def test_final_phase_raises_minors_to_blocking(self):
        text = self.loop_step("c")
        for word in (
            "raises a minor finding to blocking when it contradicts a decision on the map",
            "or when it shows a requirement that no test can check",
        ):
            self.assertIn(word, text)
        for word in (
            "the session that runs the loop",
            "that session is the main section 7 session, or the worker in step 5.3",
        ):
            self.assertIn(word, self.loop_block)

    def test_cap_stops_and_asks(self):
        self.assertIn("at any cap, stop and ask the user", self.loop_step("d"))
        for step_text in (self.step41.lower(), self.step53.lower()):
            self.assertIn("same plan-review loop as in step 3", step_text)

    def test_loop_names_its_differences_from_section_6(self):
        self.assertIn("differs from section 6 on purpose in two ways", self.loop_block)
        self.assertIn("it has no verifier subagent", self.loop_block)

    def test_step_53_uses_the_step_3_loop(self):
        self.assertIn("same plan-review loop as in step 3", self.step53.lower())

    def test_evidence_sentence_covers_the_loop_phases(self):
        sentence = sentence_with(self.section7, "section 6 loop")
        self.assertIn("round count of each", sentence)
        self.assertIn("plan-review loop", sentence)

    def test_evidence_covers_the_step_41_review(self):
        sentence = sentence_with(self.section7, "step 4.1", "checks")
        for phrase in ("plan-review loop", "result", "round count of each", "model of each"):
            self.assertIn(phrase, sentence)

    def test_section_11_lists_both_review_kinds(self):
        lines = section(self.text, 11)
        plan = [line for line in lines if "/plan-review" in line]
        code = [line for line in lines if CODE_REVIEW in line]
        self.assertEqual(len(plan), 1)
        self.assertEqual(len(code), 1)
        self.assertIn("steps 3, 4.1 and 5.3", plan[0])
        self.assertIn("section 6", code[0])
        self.assertIn("5.5", code[0])

    def test_section_6_and_step_55_keep_code_review(self):
        self.assertIn(CODE_REVIEW, "\n".join(section(self.text, 6)))
        self.assertIn(CODE_REVIEW, step(self.section7, "5.5"))


if __name__ == "__main__":
    unittest.main()
