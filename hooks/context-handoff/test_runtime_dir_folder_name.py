import os
import stat
import unittest

from test_runtime_dir import DriverTestCase  # the driver helpers; discovery puts this folder on the search path

NAME = "claude-workflow-audit"
PATH_OF_NAME = f"print(json.dumps(runtime_dir.runtime_dir_path({NAME!r})))"


class FolderNamePathTest(DriverTestCase):
    def test_no_argument_gives_the_context_handoff_folder_as_today(self):
        body = "print(json.dumps([runtime_dir.runtime_dir_path(), runtime_dir.runtime_dir_path(runtime_dir.FOLDER_NAME)]))"
        expected = os.path.join(self.tmp, "claude-context-handoff")
        self.assertEqual(self.drive(body), [expected, expected])

    def test_a_folder_name_replaces_only_the_last_component(self):
        self.assertEqual(self.drive(PATH_OF_NAME), os.path.join(self.tmp, NAME))

    def test_relative_or_empty_tmpdir_falls_back_to_tmp_without_touching_the_working_directory(self):
        work = os.path.join(self.root, "work")
        os.mkdir(work)
        for tmpdir in ("relative/dir", ""):
            with self.subTest(tmpdir=tmpdir):
                self.assertEqual(self.drive(PATH_OF_NAME, cwd=work, TMPDIR=tmpdir), "/tmp/" + NAME)
                self.assertEqual(os.listdir(work), [])

    def test_unset_tmpdir_falls_back_to_tmp(self):
        self.assertEqual(self.drive(PATH_OF_NAME, TMPDIR=None), "/tmp/" + NAME)

    def test_a_tmpdir_that_is_not_normalized_gives_a_normalized_path(self):
        for tmpdir in (self.tmp + "/./x", self.tmp + "//x", self.tmp + "/y/../x"):
            with self.subTest(tmpdir=tmpdir):
                self.assertEqual(self.drive(PATH_OF_NAME, TMPDIR=tmpdir), os.path.join(self.tmp, "x", NAME))

    def test_a_name_that_is_not_one_path_component_is_refused_and_nothing_is_made(self):
        body = f"""
            names = ["", ".", "..", "a/b", "/abs", "../escape", "nul\\0name"]
            result = {{}}
            for name in names:
                try:
                    runtime_dir.open_runtime_dir(runtime_dir.runtime_dir_path(name))
                    result[name] = "opened"
                except ValueError:
                    result[name] = "refused"
            result["listing"] = sorted(os.listdir(os.environ["TMPDIR"]))
            print(json.dumps(result))
        """
        result = self.drive(body)
        self.assertEqual(result.pop("listing"), [])
        self.assertEqual(set(result.values()), {"refused"})
        self.assertEqual(len(result), 7)


class FolderNameSafetyTest(DriverTestCase):
    """The folder-open function applies the same checks to the path of any folder name."""

    def setUp(self):
        super().setUp()
        self.folder = os.path.join(self.tmp, NAME)

    def opens(self):
        return self.drive(f"print(json.dumps(runtime_dir.open_runtime_dir(runtime_dir.runtime_dir_path({NAME!r})) is not None))")

    def test_missing_folder_is_created_with_mode_0700(self):
        self.assertTrue(self.opens())
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)

    def test_existing_safe_folder_opens(self):
        os.mkdir(self.folder, 0o700)
        self.assertTrue(self.opens())

    def test_symlink_is_unsafe(self):
        target = os.path.join(self.root, "target")
        os.mkdir(target, 0o700)
        os.symlink(target, self.folder)
        self.assertFalse(self.opens())

    def test_wider_mode_is_unsafe_and_not_repaired(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o755)
        self.assertFalse(self.opens())
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o755)

    def test_extra_mode_bit_is_unsafe(self):
        os.mkdir(self.folder)
        os.chmod(self.folder, 0o2700)
        self.assertFalse(self.opens())

    def test_regular_file_is_unsafe(self):
        with open(self.folder, "w"):
            pass
        self.assertFalse(self.opens())

    def test_other_owner_is_unsafe(self):
        # As in the existing test, the driver makes os.geteuid report another user (test code only).
        os.mkdir(self.folder, 0o700)
        body = f"""
            path = runtime_dir.runtime_dir_path({NAME!r})
            os.geteuid = lambda: os.stat(path).st_uid + 1
            print(json.dumps(runtime_dir.open_runtime_dir(path) is not None))
        """
        self.assertFalse(self.drive(body))


if __name__ == "__main__":
    unittest.main()
