import os
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GITIGNORE = os.path.join(HERE, "..", "..", ".gitignore")
FOLDER = "hooks/bash-reader"


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

    def test_the_folder_and_its_python_files_are_allow_listed(self):
        for path in ("bash_reader.py", "test_shared_bash_reader.py", "test_bash_reader_gitignore.py"):
            with self.subTest(path):
                self.assertFalse(self.ignored(f"{FOLDER}/{path}"))

    def test_compiled_files_stay_ignored(self):
        self.assertTrue(self.ignored(f"{FOLDER}/__pycache__/bash_reader.cpython-312.pyc"))

    def test_other_new_folders_are_still_ignored(self):
        for path in ("hooks/other-folder/file.py", "hooks/bash-reader-copy/bash_reader.py"):
            with self.subTest(path):
                self.assertTrue(self.ignored(path))


if __name__ == "__main__":
    unittest.main()
