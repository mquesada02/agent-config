import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CLAUDE_MD = os.path.join(REPO, "CLAUDE.md")
SKILL = os.path.join(HERE, "SKILL.md")
SPEC_AXES = os.path.join(HERE, "spec-axes.md")
STEP_PREFIX = re.compile(r"^\d+(\.\d+)?\. ")
LOOP_MARKER = "plan-review loop:"
CODE_REVIEW = "/mattpocock-skills:code-review"


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def section(text, number):
    """Text of the section whose heading starts with `## <number>.`, up to the next `## ` heading."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"## {number}."))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def step(lines, prefix):
    """Lines of a section 7 step: from its number prefix to the next line that starts a step."""
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{prefix}. "))
    end = next((i for i in range(start + 1, len(lines)) if STEP_PREFIX.match(lines[i])), len(lines))
    return "\n".join(lines[start:end])


class SkillFilesTest(unittest.TestCase):
    def test_frontmatter_names_plan_review(self):
        text = read(SKILL)
        match = re.match(r"---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(match, "SKILL.md has no frontmatter")
        fields = dict(line.split(": ", 1) for line in match.group(1).splitlines() if ": " in line)
        self.assertEqual(fields.get("name"), "plan-review")
        description = fields.get("description", "").lower()
        self.assertIn("spec", description)
        self.assertIn("ticket breakdown", description)

    def test_process_names_inputs_per_case(self):
        text = read(SKILL).lower()
        for word in ("general", "ticket", "decision tickets", "request", "map", "quote"):
            self.assertIn(word, text)

    def test_process_stops_and_asks(self):
        text = read(SKILL).lower()
        self.assertIn("stop and ask", text)
        for word in ("missing", "unknown", "`tickets`"):
            self.assertIn(word, text)

    def test_process_requires_sonnet_and_report_shape(self):
        text = read(SKILL).lower()
        for word in ("sonnet", "blocking", "minor", "counts", "most severe", "no findings"):
            self.assertIn(word, text)

    def test_spec_axes_reference_names_three_axes(self):
        text = read(SPEC_AXES)
        headings = re.findall(r"^## (.+)$", text, re.M)
        self.assertEqual(headings, ["Fidelity", "Clarity", "Codebase fit"])


class ClaudeMdWiringTest(unittest.TestCase):
    def setUp(self):
        self.text = read(CLAUDE_MD)
        self.section7 = section(self.text, 7)
        self.step3 = step(self.section7, "3")
        self.step53 = step(self.section7, "5.3")

    def test_steps_name_plan_review_spec_and_not_code_review(self):
        for text in (self.step3, self.step53):
            self.assertIn("/plan-review spec", text)
            self.assertNotIn(CODE_REVIEW, text)

    def test_steps_name_the_case_and_who_applies_fixes(self):
        self.assertIn("/plan-review spec general", self.step3)
        self.assertIn("/plan-review spec ticket", self.step53)
        self.assertIn("main section 7 session", self.step3.lower())
        self.assertIn("before any dispatch", self.step3.lower())
        self.assertIn("spec issue body", self.step3.lower())
        self.assertIn("worker", self.step53.lower())
        self.assertIn("spec issue body", self.step53.lower())

    def test_both_steps_use_the_loop(self):
        for text in (self.step3, self.step53):
            self.assertIn("plan-review loop", text.lower())

    def test_loop_block_is_stated_once_in_step_3(self):
        markers = [line for line in self.section7 if line.lower().startswith(LOOP_MARKER)]
        self.assertEqual(len(markers), 1)
        block = self.step3.lower().split(LOOP_MARKER, 1)[1]
        for word in (
            "correctness phase", "final phase", "2 consecutive rounds", "no blocking",
            "apply the recorded minor", "list", "count at zero",
        ):
            self.assertIn(word, block)
        self.assertEqual(re.findall(r"^\(([a-d])\) ", block, re.M), ["a", "b", "c", "d"])

    def test_step_3_says_no_simplify_and_differs_from_section_6(self):
        text = self.step3.lower()
        self.assertIn("/simplify", text)
        self.assertIn("no ", text.split("/simplify")[0][-30:])
        self.assertIn("differs from section 6", text)

    def test_step_53_states_the_restart_rule(self):
        self.assertIn("count at zero", self.step53.lower())

    def test_evidence_sentence_covers_the_loop_phases(self):
        sentences = [
            sentence
            for sentence in re.split(r"(?<=[.])\s+", " ".join(self.section7))
            if "round count of each" in sentence
        ]
        self.assertEqual(len(sentences), 1)
        self.assertIn("plan-review loop", sentences[0].lower())

    def test_section_11_lists_both_review_kinds(self):
        lines = section(self.text, 11)
        plan = [line for line in lines if "/plan-review" in line]
        code = [line for line in lines if CODE_REVIEW in line]
        self.assertEqual(len(plan), 1)
        self.assertEqual(len(code), 1)
        self.assertIn("steps 3 and 5.3", plan[0])
        self.assertIn("section 6", code[0])
        self.assertIn("5.5", code[0])

    def test_section_6_and_step_55_keep_code_review(self):
        self.assertIn(CODE_REVIEW, "\n".join(section(self.text, 6)))
        self.assertIn(CODE_REVIEW, step(self.section7, "5.5"))


if __name__ == "__main__":
    unittest.main()
