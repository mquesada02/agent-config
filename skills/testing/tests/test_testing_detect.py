import json
import os
import subprocess
import sys
import unittest

import helper_testing_rules as helper
from helper_testing_rules import doc

CARGO = '[package]\nname = "app"\n'
PKG_VITEST = '{"devDependencies": {"vitest": "1"}}'
EMPTY = {"languages": [], "entries": {}, "facts": {}}


def lang(name, root, manifest):
    return {"name": name, "root": root, "manifest": manifest}


def rules_block(*pairs):
    """A rules file with only [[languages]] entries: pairs of (name, root)."""
    return "".join(f'[[languages]]\nname = "{name}"\nroot = "{root}"\n\n' for name, root in pairs)


@unittest.skipUnless(sys.version_info >= (3, 11), "the script needs tomllib (Python 3.11 or newer)")
class DetectCase(unittest.TestCase):
    def setUp(self):
        self.repo = helper.Repo()
        self.addCleanup(self.repo.close)

    def run_cli(self, *files):
        done = helper.run_script(self.repo.root, *files)
        return done, (json.loads(done.stdout) if done.stdout else None)

    def detect(self, *files, code=0):
        done, data = self.run_cli(*files)
        self.assertEqual(done.returncode, code, done.stderr)
        return data["detected"]

    def facts(self, language, *files):
        return self.detect(*files)["facts"][language]

    def assert_fact(self, fact, value, status):
        self.assertEqual((fact["value"], fact["status"]), (value, status), fact)
        self.assertTrue(fact["source"])

    def rules_file(self, *pairs, extra=""):
        self.repo.write(doc(rules_block(*pairs) + extra))


class RustFactsTest(DetectCase):
    def nextest_repo(self):
        self.repo.put("Cargo.toml", CARGO + '[dev-dependencies]\nproptest = "1"\ninsta = "1"\nmockall = "1"\ntokio = "1"\n'
                      '[[test]]\nname = "a"\nrequired-features = ["zeta", "alpha"]\n')
        self.repo.put("src/lib.rs", "")
        self.repo.put(".config/nextest.toml",
                      '[profile.default]\n[profile.ci]\nretries = 2\nslow-timeout = "60s"\nglobal-timeout = "5m"\n'
                      '[test-groups.db]\nmax-threads = 1\n')
        self.repo.put("tests/sub/x.rs", "")
        self.repo.put("crates/b/src/a/b.rs", "#[cfg(test)]\n")

    def test_nextest_commands_and_runner(self):
        self.nextest_repo()
        facts = self.facts("rust")
        self.assert_fact(facts["runner"]["name"], "nextest", "detected")
        self.assert_fact(facts["commands"]["test"], "cargo nextest run", "detected")
        self.assert_fact(facts["commands"]["worker_flag"], "-j", "default")
        self.assert_fact(facts["commands"]["changed"], None, "default")
        self.assert_fact(facts["commands"]["doc"], "cargo test --doc", "detected")
        self.assert_fact(facts["runner"]["profiles"], ["ci", "default"], "detected")
        self.assert_fact(facts["runner"]["test_groups"], ["db"], "detected")
        self.assert_fact(facts["runner"]["retries"], {"ci": 2}, "detected")
        self.assert_fact(facts["runner"]["timeouts"], {"ci": {"slow-timeout": "60s", "global-timeout": "5m"}}, "detected")
        self.assert_fact(facts["runner"]["features"], ["alpha", "zeta"], "detected")

    def test_layout_libraries_groups_limits(self):
        self.nextest_repo()
        facts = self.facts("rust")
        self.assert_fact(facts["layout"]["test_paths"], ["crates/b/src", "tests"], "detected")
        self.assert_fact(facts["layout"]["file_pattern"], ["tests/*.rs", "#[cfg(test)] modules"], "default")
        self.assert_fact(facts["layout"]["setup_files"], [], "default")
        self.assert_fact(facts["layout"]["members"], ["app"], "detected")
        library = facts["libraries"]
        self.assert_fact(library["property"], "proptest", "detected")
        self.assert_fact(library["snapshot"], "insta", "detected")
        self.assert_fact(library["fakes"], "mockall", "detected")
        self.assert_fact(library["async"], "tokio", "detected")
        self.assert_fact(library["commit_regressions"], True, "default")
        self.assert_fact(library["commit_snapshots"], True, "default")
        self.assert_fact(facts["groups"], [], "unknown")
        self.assert_fact(facts["limits"]["small_ms"], 100, "default")
        self.assert_fact(facts["limits"]["medium_ms"], 1000, "default")

    def test_gitignore_sets_the_commit_facts(self):
        self.nextest_repo()
        self.repo.put(".gitignore", "# note\n/proptest-regressions/\n!x\n**/*.snap\n")
        library = self.facts("rust")["libraries"]
        self.assert_fact(library["commit_regressions"], False, "detected")
        self.assert_fact(library["commit_snapshots"], False, "detected")

    def test_plain_cargo_test(self):
        self.repo.put("Cargo.toml", CARGO)
        facts = self.facts("rust")
        self.assert_fact(facts["runner"]["name"], "cargo test", "default")
        self.assert_fact(facts["commands"]["test"], "cargo test", "default")
        self.assert_fact(facts["commands"]["worker_flag"], "-- --test-threads", "default")
        self.assertEqual(facts["commands"]["doc"], {"value": None, "status": "default", "source": "cargo test runs doc tests"})
        self.assert_fact(facts["runner"]["profiles"], [], "default")
        self.assert_fact(facts["runner"]["retries"], {}, "default")
        self.assert_fact(facts["runner"]["features"], [], "detected")
        self.assert_fact(facts["libraries"]["property"], None, "detected")
        self.assert_fact(facts["libraries"]["commit_regressions"], None, "detected")

    def test_doc_command_reasons_under_nextest(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put(".config/nextest.toml", "")
        self.assertEqual(self.facts("rust")["commands"]["doc"],
                         {"value": None, "status": "default", "source": "no src/lib.rs"})
        self.repo.put("src/lib.rs", "")
        self.repo.put("Cargo.toml", CARGO + "[lib]\ndoctest = false\n")
        self.assertEqual(self.facts("rust")["commands"]["doc"],
                         {"value": None, "status": "default", "source": "doctest = false"})

    def test_workspace_members_and_member_manifest_features(self):
        self.repo.put("Cargo.toml", '[workspace]\nmembers = ["crates/*", "tools/x"]\n')
        self.repo.put("crates/a/Cargo.toml", '[[test]]\nname = "t"\nrequired-features = ["f1"]\n')
        self.repo.put("tools/x/Cargo.toml", '[dev-dependencies]\nquickcheck = "1"\n')
        facts = self.facts("rust")
        self.assert_fact(facts["layout"]["members"], ["crates/*", "tools/x"], "detected")
        self.assert_fact(facts["runner"]["features"], ["f1"], "detected")
        self.assert_fact(facts["libraries"]["property"], "quickcheck", "detected")

    def test_missing_listed_member_makes_manifest_facts_unknown(self):
        self.repo.put("Cargo.toml", '[workspace]\nmembers = ["gone"]\n')
        facts = self.facts("rust")
        self.assert_fact(facts["runner"]["features"], [], "unknown")
        self.assert_fact(facts["libraries"]["property"], None, "unknown")
        self.assert_fact(facts["libraries"]["commit_regressions"], None, "unknown")
        self.assert_fact(facts["layout"]["members"], ["gone"], "detected")

    def test_invalid_nextest_file(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put(".config/nextest.toml", "[profile\n")
        runner = self.facts("rust")["runner"]
        self.assert_fact(runner["profiles"], [], "unknown")
        self.assert_fact(runner["test_groups"], [], "unknown")
        self.assert_fact(runner["retries"], {}, "unknown")
        self.assert_fact(runner["timeouts"], {}, "unknown")

    def test_invalid_cargo_toml(self):
        self.repo.put("Cargo.toml", "[package\n")
        self.repo.put("tests/a.rs", "")
        layout = self.facts("rust")["layout"]
        self.assert_fact(layout["members"], [], "unknown")
        self.assert_fact(layout["test_paths"], ["tests"], "detected")

    def test_nan_and_date_values_are_text(self):
        self.repo.put("Cargo.toml", "[workspace]\nmembers = [nan]\n")
        self.assert_fact(self.facts("rust")["layout"]["members"], ["nan"], "detected")
        self.repo.put("Cargo.toml", "[workspace]\nmembers = [1979-05-27]\n")
        self.repo.write("```toml\nx = [\n```\n")
        done, data = self.run_cli()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["detected"]["facts"]["rust"]["layout"]["members"]["value"], ["1979-05-27"])

    def test_non_utf8_files_are_skipped(self):
        self.repo.put("Cargo.toml", '[workspace]\nmembers = ["crates/b"]\n[dev-dependencies]\nproptest = "1"\n')
        self.repo.put("crates/b/Cargo.toml", CARGO)
        self.repo.put("src/ok.rs", "#[cfg(test)]\n")
        self.repo.put("crates/b/src/bad.rs", b"\xff\xfe#[cfg(test)]")
        self.repo.put(".gitignore", b"\xff\xfe\nproptest-regressions\n")
        facts = self.facts("rust")
        self.assert_fact(facts["layout"]["test_paths"], ["src"], "detected")
        self.assert_fact(facts["libraries"]["commit_regressions"], True, "detected")

    def test_nextest_without_manifest_has_unknown_doc(self):
        self.repo.write(doc(rules_block(("rust", "crates"))))
        self.repo.put("crates/.config/nextest.toml", "")
        facts = self.facts("rust")
        self.assertEqual(facts["commands"]["doc"], {"value": None, "status": "unknown", "source": "no Cargo.toml"})
        os.remove(os.path.join(self.repo.root, "crates", ".config", "nextest.toml"))
        self.assertEqual(self.facts("rust")["commands"]["doc"],
                         {"value": None, "status": "default", "source": "cargo test runs doc tests"})

    def test_rules_root_without_manifest_has_unknown_manifest_facts(self):
        self.repo.write(doc(rules_block(("rust", "crates"))))
        self.repo.put("crates/a.txt", "")
        detected = self.detect()
        self.assertEqual(detected["languages"], [lang("rust", "crates", None)])
        facts = detected["facts"]["rust"]
        self.assert_fact(facts["runner"]["features"], [], "unknown")
        self.assert_fact(facts["layout"]["members"], [], "unknown")
        for key in ("property", "snapshot", "fakes", "async"):
            self.assert_fact(facts["libraries"][key], None, "unknown")
        self.assert_fact(facts["libraries"]["commit_regressions"], None, "unknown")
        self.assert_fact(facts["libraries"]["commit_snapshots"], None, "unknown")


@unittest.skipUnless(hasattr(os, "mkfifo"), "needs named pipes")
class SpecialFilesTest(DetectCase):
    def run_with_timeout(self):
        done = subprocess.run(
            [sys.executable, "-I", helper.SCRIPT, self.repo.root],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)["detected"]["facts"]

    def test_named_pipe_test_file_does_not_hang_the_typescript_scan(self):
        self.repo.put("package.json", PKG_VITEST)
        os.mkfifo(os.path.join(self.repo.root, "a.test.js"))
        facts = self.run_with_timeout()
        self.assert_fact(facts["typescript"]["layout"]["test_paths"], ["."], "detected")

    def test_named_pipe_rust_file_does_not_hang_the_rust_scan(self):
        self.repo.put("Cargo.toml", CARGO)
        os.makedirs(os.path.join(self.repo.root, "src"))
        os.mkfifo(os.path.join(self.repo.root, "src", "x.rs"))
        facts = self.run_with_timeout()
        self.assert_fact(facts["rust"]["layout"]["test_paths"], [], "detected")


class TypeScriptFactsTest(DetectCase):
    def test_vitest_facts(self):
        self.repo.put("package.json", '{"devDependencies": {"vitest": "1", "typescript": "5", "msw": "2", "nock": "1", "fast-check": "3"},'
                      ' "engines": {"node": ">=20"}, "type": "module", "packageManager": "pnpm@9.1.0"}')
        self.repo.put("src/a.test.ts", "")
        self.repo.put("test/__snapshots__/a.snap", "")
        self.repo.put(".gitignore", "node_modules\n")
        facts = self.facts("typescript")
        self.assert_fact(facts["runner"]["name"], "vitest", "detected")
        self.assert_fact(facts["commands"]["test"], "pnpm exec vitest run", "detected")
        self.assert_fact(facts["commands"]["worker_flag"], "--maxWorkers", "default")
        self.assert_fact(facts["commands"]["changed"], "--changed", "default")
        self.assert_fact(facts["commands"]["typecheck"], "pnpm exec tsc --noEmit", "default")
        self.assert_fact(facts["runner"]["package_manager"], "pnpm", "detected")
        self.assert_fact(facts["runner"]["node_version"], ">=20", "detected")
        self.assertEqual(facts["runner"]["node_version"]["source"], "package.json engines.node")
        self.assert_fact(facts["runner"]["module_format"], "esm", "detected")
        self.assert_fact(facts["layout"]["test_paths"], ["src"], "detected")
        self.assert_fact(facts["layout"]["file_pattern"], ["**/*.{test,spec}.?(c|m)[jt]s?(x)"], "default")
        self.assert_fact(facts["layout"]["setup_files"], [], "unknown")
        self.assert_fact(facts["libraries"]["property"], "fast-check", "detected")
        self.assert_fact(facts["libraries"]["fakes"], ["msw", "nock"], "detected")
        self.assert_fact(facts["libraries"]["snapshot"], "vitest", "detected")
        self.assert_fact(facts["libraries"]["async"], None, "default")
        self.assert_fact(facts["libraries"]["commit_regressions"], None, "default")
        self.assert_fact(facts["libraries"]["commit_snapshots"], True, "detected")
        self.assert_fact(facts["groups"], [], "unknown")
        self.assert_fact(facts["limits"]["small_ms"], 100, "default")

    def test_jest_facts(self):
        self.repo.put("package.json", '{"devDependencies": {"jest": "29"}, "scripts": {"type-check": "tsc", "tsc": "tsc"}}')
        self.repo.put("yarn.lock", "")
        self.repo.put("src/__tests__/a.ts", "")
        self.repo.put(".gitignore", "__snapshots__/\n")
        self.repo.put("src/a.snap", "")
        facts = self.facts("typescript")
        self.assert_fact(facts["commands"]["test"], "yarn jest --ci", "detected")
        self.assert_fact(facts["commands"]["changed"], "--onlyChanged", "default")
        self.assert_fact(facts["commands"]["typecheck"], "yarn run type-check", "detected")
        self.assert_fact(facts["runner"]["package_manager"], "yarn", "detected")
        self.assert_fact(facts["layout"]["test_paths"], ["src"], "detected")
        self.assert_fact(facts["libraries"]["snapshot"], "jest", "detected")
        self.assert_fact(facts["libraries"]["commit_snapshots"], False, "detected")

    def test_node_test_by_script_and_by_import(self):
        self.repo.put("package.json", '{"scripts": {"test": "node --test"}}')
        facts = self.facts("typescript")
        self.assert_fact(facts["runner"]["name"], "node:test", "detected")
        self.assert_fact(facts["commands"]["test"], "node --test", "detected")
        self.assert_fact(facts["commands"]["worker_flag"], "--test-concurrency", "default")
        self.assert_fact(facts["commands"]["changed"], None, "default")
        self.assertEqual(facts["layout"]["file_pattern"]["value"][0], "*.test")
        self.repo.put("package.json", "{}")
        self.repo.put("a.test.js", 'import test from "node:test";\n')
        self.assert_fact(self.facts("typescript")["runner"]["name"], "node:test", "detected")

    def test_both_runners_follow_the_test_script(self):
        self.repo.put("package.json", '{"devDependencies": {"vitest": "1", "jest": "29"}, "scripts": {"test": "jest"}}')
        self.assert_fact(self.facts("typescript")["runner"]["name"], "jest", "detected")
        self.repo.put("package.json", '{"devDependencies": {"vitest": "1", "jest": "29"}}')
        self.assert_fact(self.facts("typescript")["runner"]["name"], "vitest", "detected")

    def test_no_runner_makes_dependent_facts_unknown(self):
        self.repo.put("package.json", "{}")
        self.repo.put(".gitignore", "*.snap\n")
        facts = self.facts("typescript")
        self.assert_fact(facts["runner"]["name"], None, "unknown")
        for key in ("test", "worker_flag", "changed"):
            self.assert_fact(facts["commands"][key], None, "unknown")
        self.assert_fact(facts["layout"]["file_pattern"], None, "unknown")
        self.assert_fact(facts["libraries"]["snapshot"], None, "unknown")
        self.assert_fact(facts["libraries"]["commit_snapshots"], None, "unknown")
        self.assertEqual(facts["commands"]["typecheck"]["source"],
                         "no typecheck script, no typescript dependency, no tsconfig.json")
        self.assert_fact(facts["commands"]["typecheck"], None, "default")
        self.assert_fact(facts["libraries"]["fakes"], [], "detected")

    def test_node_version_file_order(self):
        self.repo.put("package.json", '{"engines": {"node": "18"}}')
        self.repo.put("web/package.json", "{}")
        self.repo.write(doc(rules_block(("typescript", "web"))))
        self.repo.put(".nvmrc", "\n v20.1.0 \n")
        self.repo.put("web/.node-version", "22\n")
        version = self.facts("typescript")["runner"]["node_version"]
        self.assertEqual((version["value"], version["source"]), ("v20.1.0", ".nvmrc"))

    def test_typecheck_script_name_order_and_tsconfig(self):
        self.repo.put("package.json", '{"scripts": {"tsc": "tsc", "typecheck": "tsc -b"}}')
        self.assert_fact(self.facts("typescript")["commands"]["typecheck"], "npm run typecheck", "detected")
        self.repo.put("package.json", "{}")
        self.repo.put("tsconfig.json", "{}")
        self.assert_fact(self.facts("typescript")["commands"]["typecheck"], "npx tsc --noEmit", "default")

    def test_unparseable_package_json(self):
        self.repo.put("package.json", "{")
        self.repo.put("pnpm-lock.yaml", "")
        facts = self.facts("typescript")
        self.assert_fact(facts["runner"]["package_manager"], "pnpm", "detected")
        self.assert_fact(facts["runner"]["module_format"], "commonjs", "default")
        self.assert_fact(facts["libraries"]["fakes"], [], "unknown")
        self.assertEqual(facts["commands"]["typecheck"]["status"], "unknown")
        self.assertEqual(facts["commands"]["typecheck"]["source"], "package.json is not valid JSON")
        self.repo.put("tsconfig.json", "{}")
        self.assertEqual(self.facts("typescript")["commands"]["typecheck"]["status"], "default")

    def test_binary_lockfile_counts_as_present(self):
        self.repo.put("package.json", "{}")
        self.repo.put("bun.lockb", b"\xff\xfe")
        self.assert_fact(self.facts("typescript")["runner"]["package_manager"], "bun", "detected")

    def test_nan_engines_is_text(self):
        self.repo.put("package.json", '{"engines": {"node": NaN}}')
        self.assert_fact(self.facts("typescript")["runner"]["node_version"], "nan", "detected")

    def test_config_code_is_never_run(self):
        self.repo.put("package.json", PKG_VITEST)
        self.repo.put("vitest.config.js", 'throw new Error("run");\n')
        self.assert_fact(self.facts("typescript")["runner"]["name"], "vitest", "detected")

    def test_rules_root_without_manifest(self):
        self.repo.write(doc(rules_block(("typescript", "web"))))
        facts = self.facts("typescript")
        self.assert_fact(facts["runner"]["name"], None, "unknown")
        self.assert_fact(facts["libraries"]["property"], None, "unknown")
        self.assert_fact(facts["libraries"]["fakes"], [], "unknown")
        self.assert_fact(facts["libraries"]["commit_snapshots"], None, "unknown")
        self.assert_fact(facts["commands"]["typecheck"], None, "default")
        for key in ("test", "worker_flag", "changed"):
            self.assert_fact(facts["commands"][key], None, "unknown")
        self.assert_fact(facts["layout"]["file_pattern"], None, "unknown")
        self.assert_fact(facts["libraries"]["snapshot"], None, "unknown")


class LanguagesAndRoutingTest(DetectCase):
    def test_no_manifest_and_no_rules(self):
        self.repo.put("a.txt", "")
        self.assertEqual(self.detect("a.txt"), {"languages": [], "entries": {"a.txt": "general"}, "facts": {}})

    def test_mixed_repo_routes_each_file(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put("web/package.json", PKG_VITEST)
        detected = self.detect("src/lib.rs", "web/src/a.ts", "README.md")
        self.assertEqual(detected["languages"], [lang("rust", ".", "Cargo.toml"), lang("typescript", "web", "web/package.json")])
        self.assertEqual(detected["entries"], {"src/lib.rs": "rust", "web/src/a.ts": "typescript", "README.md": "rust"})
        self.assertEqual(sorted(detected["facts"]), ["rust", "typescript"])

    def test_both_manifests_in_one_folder_use_the_extension(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put("package.json", PKG_VITEST)
        entries = self.detect("a.rs", "b.tsx", "c.mjs", "d.md")["entries"]
        self.assertEqual(entries, {"a.rs": "rust", "b.tsx": "typescript", "c.mjs": "typescript", "d.md": "general"})

    def test_go_mod_stops_the_walk(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put("go/go.mod", "")
        self.assertEqual(self.detect("go/main.go", "x.rs")["entries"], {"go/main.go": "general", "x.rs": "rust"})

    def test_go_only_repo(self):
        self.repo.put("go.mod", "")
        self.assertEqual(self.detect("main.go"), {"languages": [], "entries": {"main.go": "general"}, "facts": {}})

    def test_node_modules_file_routes_by_its_manifest(self):
        self.repo.put("package.json", PKG_VITEST)
        self.repo.put("node_modules/x/index.js", "")
        entries = self.detect("node_modules/x/index.js")["entries"]
        self.assertEqual(entries, {"node_modules/x/index.js": "typescript"})

    def test_manifest_search_skips_vendored_folders_and_takes_the_shallowest(self):
        self.repo.put("node_modules/p/package.json", "{}")
        self.repo.put("b/package.json", PKG_VITEST)
        self.repo.put("a/c/package.json", PKG_VITEST)
        self.assertEqual(self.detect()["languages"], [lang("typescript", "b", "b/package.json")])
        self.repo.put("a/package.json", PKG_VITEST)
        self.assertEqual(self.detect()["languages"], [lang("typescript", "a", "a/package.json")])

    def test_rules_root_wins_over_the_nearest_manifest(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put("web/package.json", PKG_VITEST)
        self.rules_file(("typescript", "."))
        detected = self.detect("src/lib.rs", "web/a.ts")
        self.assertEqual(detected["entries"], {"src/lib.rs": "typescript", "web/a.ts": "typescript"})
        self.assertEqual(detected["languages"][1], lang("typescript", ".", None))

    def test_rules_roots_are_normalised(self):
        self.repo.put("web/package.json", PKG_VITEST)
        self.rules_file(("typescript", "./a/../web/"))
        self.assertEqual(self.detect()["languages"], [lang("typescript", "web", "web/package.json")])

    def test_invalid_rules_entries_are_ignored(self):
        self.repo.put("Cargo.toml", CARGO)
        self.rules_file(("rust", "../x"), ("rust", "/abs"), ("go", "."))
        self.assertEqual(self.detect("a.rs")["languages"], [lang("rust", ".", "Cargo.toml")])

    def test_rules_root_with_a_nul_character_is_ignored(self):
        for name in ("rust", "typescript"):
            with self.subTest(name):
                self.repo.write("```toml\n[[languages]]\nname = \"" + name + "\"\nroot = \"a\\u0000b\"\n```\n")
                self.assertEqual(self.detect("a.rs")["languages"], [])

    def test_rules_error_skips_the_rules_roots(self):
        self.repo.put("Cargo.toml", CARGO)
        self.repo.put("web/package.json", PKG_VITEST)
        self.repo.write("```toml\n" + rules_block(("typescript", ".")) + "x = [\n```\n")
        done, data = self.run_cli("src/lib.rs", "web/a.ts")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(data["detected"]["entries"], {"src/lib.rs": "rust", "web/a.ts": "typescript"})
        self.assertEqual(data["detected"]["languages"],
                         [lang("rust", ".", "Cargo.toml"), lang("typescript", "web", "web/package.json")])

    def test_shared_root_uses_the_extension(self):
        self.repo.put("Cargo.toml", CARGO)
        self.rules_file(("rust", "."), ("typescript", "."))
        entries = self.detect("a.rs", "b.ts", "c.md")["entries"]
        self.assertEqual(entries, {"a.rs": "rust", "b.ts": "typescript", "c.md": "general"})

    def test_longest_rules_root_wins_and_a_second_entry_counts_for_routing(self):
        self.rules_file(("rust", "a"), ("typescript", "a/b"), ("rust", "c"))
        detected = self.detect("a/x.ts", "a/b/y.rs", "c/z.md", "d/w.rs")
        self.assertEqual(detected["entries"], {"a/x.ts": "rust", "a/b/y.rs": "typescript", "c/z.md": "rust", "d/w.rs": "general"})
        self.assertEqual(detected["languages"], [lang("rust", "a", None), lang("typescript", "a/b", None)])

    def test_missing_languages_section_counts_the_detected_languages(self):
        self.repo.put("Cargo.toml", CARGO)
        block = helper.block(drop=("languages", "commands.rust"))
        self.repo.write(doc(block))
        done, data = self.run_cli()
        self.assertEqual(done.returncode, 0)
        missing = data["rules"]["missing_sections"]
        self.assertIn("languages", missing)
        self.assertIn("commands.rust", missing)
        self.assertNotIn("commands.typescript", missing)


class PathsTest(DetectCase):
    def setUp(self):
        super().setUp()
        self.repo.put("Cargo.toml", CARGO)

    def test_relative_path_and_new_file(self):
        self.assertEqual(self.detect("tests/new.rs")["entries"], {"tests/new.rs": "rust"})

    def test_absolute_path_inside_the_root_keeps_its_key(self):
        path = os.path.join(self.repo.root, "src", "a.rs")
        self.assertEqual(self.detect(path)["entries"], {path: "rust"})

    def test_dot_dot_path_that_returns_inside(self):
        self.assertEqual(self.detect("x/../src/a.rs")["entries"], {"x/../src/a.rs": "rust"})

    def test_paths_outside_the_root_are_usage_errors(self):
        for text in ("../x.rs", "/etc/passwd", "a/../../x.rs", ""):
            with self.subTest(text):
                done, _ = self.run_cli(text)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertIn("usage", done.stderr)

    def test_invalid_path_wins_over_a_malformed_rules_file(self):
        self.repo.write("```toml\nx = [\n```\n")
        done, _ = self.run_cli("../x.rs")
        self.assertEqual(done.returncode, 2)
        self.assertEqual(done.stdout, "")


if __name__ == "__main__":
    unittest.main()
