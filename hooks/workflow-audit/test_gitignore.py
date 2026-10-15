import os
import shutil
import subprocess
import tempfile
import unittest

from audit_support import HERE

GITIGNORE = os.path.join(HERE, "..", "..", ".gitignore")
FOLDER = "hooks/workflow-audit"


class AllowListTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copy(GITIGNORE, os.path.join(self.root, ".gitignore"))
        subprocess.run(["git", "init", "-q", self.root], check=True, env={"PATH": os.environ["PATH"], "HOME": self.root})

    def ignored(self, path):
        result = subprocess.run(["git", "-C", self.root, "check-ignore", "-q", path], env={"PATH": os.environ["PATH"], "HOME": self.root})
        self.assertIn(result.returncode, (0, 1))
        return result.returncode == 0

    def test_the_folder_and_everything_below_it_are_allow_listed(self):
        for path in ("audit", "test_audit.py", "fixtures/transcript.jsonl", "fixtures/deep/er/file.json", "fixtures/README.md", "notes.txt"):
            with self.subTest(path):
                self.assertFalse(self.ignored(f"{FOLDER}/{path}"))

    def test_compiled_files_stay_ignored(self):
        for path in (f"{FOLDER}/__pycache__/audit_support.cpython-312.pyc", f"{FOLDER}/fixtures/__pycache__/x.pyc"):
            with self.subTest(path):
                self.assertTrue(self.ignored(path))

    def test_other_folders_are_still_ignored(self):
        self.assertTrue(self.ignored("hooks/other-folder/file.py"))


if __name__ == "__main__":
    unittest.main()
