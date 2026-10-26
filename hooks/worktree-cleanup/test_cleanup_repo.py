import os
import shutil
import subprocess
import tempfile
import unittest

from cleanup_support import CLEANUP, HERE

GITIGNORE = os.path.join(HERE, "..", "..", ".gitignore")
FOLDER = "hooks/worktree-cleanup"


class ScriptFileTest(unittest.TestCase):
    def test_the_script_is_executable_and_starts_with_a_python3_shebang(self):
        self.assertTrue(os.access(CLEANUP, os.X_OK))
        with open(CLEANUP) as f:
            self.assertEqual(f.readline().rstrip("\n"), "#!/usr/bin/env python3")


class AllowListTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copy(GITIGNORE, os.path.join(self.root, ".gitignore"))
        self.env = {"PATH": os.environ["PATH"], "HOME": self.root}
        subprocess.run(["git", "init", "-q", self.root], check=True, env=self.env)

    def ignored(self, path):
        result = subprocess.run(["git", "-C", self.root, "check-ignore", "-q", path], env=self.env)
        self.assertIn(result.returncode, (0, 1))
        return result.returncode == 0

    def test_the_folder_and_its_files_are_not_ignored(self):
        for path in ("cleanup", "cleanup_support.py", "test_cleanup_checks.py", "notes.md"):
            with self.subTest(path):
                self.assertFalse(self.ignored(f"{FOLDER}/{path}"))

    def test_compiled_files_stay_ignored(self):
        self.assertTrue(self.ignored(f"{FOLDER}/__pycache__/cleanup_support.cpython-312.pyc"))

    def test_other_folders_are_still_ignored(self):
        self.assertTrue(self.ignored("hooks/other-folder/file.py"))


if __name__ == "__main__":
    unittest.main()
