"""Run every test folder of the repo in 2 processes at the same time. Exit non-zero when either process fails.

Run it from the repo root: python3 scripts/run-tests.py

The folders are split into 2 groups of about equal measured time (docs/research/test-suite-timing.md). Each group
runs in its own process, one worker each, so the run stays inside the limit of 2 workers. A process prints its own
result after it ends. With one argument (the group number) the script runs that group in this process.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUPS = (
    ("skills/sql/tests", "skills/cicd-pipelines/tests", "hooks/worktree-cleanup", "hooks/redact-secrets",
     "hooks/bash-reader", "hooks/forked-skills", "hooks/setup-diff-prompt", "hooks/subagent-readonly",
     "hooks/worktree-branch", "skills/plan-review"),
    ("hooks/workflow-audit", "hooks/context-handoff", "skills/testing/tests"),
)


def run_group(index):
    suite = unittest.TestSuite()
    for folder in GROUPS[index]:
        suite.addTests(unittest.defaultTestLoader.discover(folder, top_level_dir=folder))
    return 0 if unittest.TextTestRunner().run(suite).wasSuccessful() else 1


def main(argv):
    os.chdir(ROOT)
    if argv:
        return run_group(int(argv[0]))
    outputs, children = [], []
    for index in range(len(GROUPS)):
        output = tempfile.TemporaryFile("w+", encoding="utf-8")
        outputs.append(output)
        children.append(subprocess.Popen([sys.executable, __file__, str(index)], stdout=output, stderr=subprocess.STDOUT))
    codes = [child.wait() for child in children]
    for index, output in enumerate(outputs):
        output.seek(0)
        print("== group %d: %s" % (index + 1, "ok" if codes[index] == 0 else "FAILED"))
        print(output.read(), end="")
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
