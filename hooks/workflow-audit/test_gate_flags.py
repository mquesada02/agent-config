import shlex
import time
import unittest

from test_dispatch_gate import DispatchGateCase
from test_gate import GateTestCase

SPELLINGS = (
    "gh -R o/r pr create --fill", "gh --repo o/r pr create --fill", "gh --repo=o/r pr create", "gh -Ro/r pr create", "gh pr -R o/r create --fill",
    "gh -R o/r pr --repo o/r create", "gh pr new --fill", "gh -R o/r pr new", "/usr/bin/gh -R o/r pr create", "env gh -R o/r pr create",
    "gh >out pr create",
)
API_DENIED = (
    "gh api -X POST repos/o/r/pulls -f title=t -f head=b -f base=main", "gh api repos/o/r/pulls -f title=t", "gh api --method=POST /repos/o/r/pulls",
    "gh api -XPOST repos/{owner}/{repo}/pulls", "gh api repos/o/r/pulls --input body.json", "gh api -X POST https://api.github.com/repos/o/r/pulls/",
    "gh -R o/r api -X POST repos/o/r/pulls", "gh api -X POST $ENDPOINT -f title=t",
    "gh api graphql -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'", "gh api graphql --input query.json",
    "gh api graphql -F query=@query.graphql", 'gh api graphql -f query="$QUERY"', "gh api -X POST repos/o/r/PULLS -f title=t",
    "gh api -X POST 'repos/o/r/pulls#x' -f title=t",
    # M16: the endpoint spelled with a trailing slash, a query or another case is the GraphQL endpoint too
    "gh api graphql/ -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    "gh api GraphQL -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    "gh api 'graphql?x=1' -f query='mutation { createPullRequest(input: {}) { clientMutationId } }'",
    "gh api /graphql/ --input query.json",
)
OVERRIDE_DENIED = (
    "gh api -H 'X-HTTP-Method-Override: POST' repos/o/r/pulls", "gh api -H 'x-http-method-override: POST' repos/o/r/pulls -f title=t",
    "gh api --method GET -H 'X-HTTP-Method-Override: POST' repos/o/r/pulls", "gh api --header 'X-HTTP-Method-Override: POST' repos/o/r/pulls",
    "gh api --header='X-HTTP-Method-Override: POST' repos/o/r/pulls", "gh api -H'X-HTTP-Method-Override: POST' repos/o/r/pulls",
    "gh api -H 'X-Http-Method-Override:POST' repos/o/r/issues", "gh api repos/o/r/issues -H 'X-HTTP-METHOD-OVERRIDE: PATCH'",
    "gh -R o/r api -H 'X-HTTP-Method-Override: POST' repos/o/r/pulls", "gh api -H \"$HEADER\" repos/o/r/pulls", "gh api -H \"X-HTTP-Method-$NAME: POST\" repos/o/r/issues",
)
OVERRIDE_ALLOWED = (
    "gh api -H 'Accept: application/vnd.github+json' repos/o/r/pulls", "gh api --header 'Authorization: Bearer '$TOKEN user",
    "gh api -H 'Accept: application/json' repos/o/r/issues --jq '.[].title'",
)
API_ALLOWED = (
    "gh api repos/o/r/pulls", "gh api repos/o/r/pulls/5", "gh api -X GET repos/o/r/pulls -f state=open", "gh api -X POST repos/o/r/issues -f title=t",
    "gh api -X POST repos/o/r/pulls/5/comments -f body=b", "gh api graphql -f query='{ viewer { login } }'", "gh api user --jq .login",
    "bash -c 'gh api user'", "echo gh api", "git commit -m 'about gh api'", "grep 'gh api' notes.md", "gh api repos/o/r/issues --jq '.[] | .title'",
)
ALIAS_DENIED = (
    "gh alias set pc 'pr create'", "gh alias set pc 'pr new --fill'", "gh alias set pc 'pr -R o/r create'", "gh alias set pc '-R o/r pr create'", "gh alias set pc '--repo=o/r pr new'","gh alias set pc -- '-R o/r pr create'",
    "gh alias set --shell pc 'gh pr create'", "gh alias set -s pc '!gh -R o/r pr create'", "gh alias set --clobber pc 'pr create'", "gh alias set pc -",
    'gh alias set pc "$EXPANSION"',
    # M8: an expansion that is a `gh api` call to pulls or GraphQL, or that lacks the endpoint (the alias call appends it), or that has an override header
    "gh alias set pc 'api -X POST repos/o/r/pulls -f title=t'", "gh alias set pc 'api repos/o/r/pulls'", "gh alias set pc 'api graphql'",
    "gh alias set pc 'api -X POST'", "gh alias set pc 'api'", "gh alias set pc '-R o/r api repos/o/r/pulls'", "gh alias set pc -- 'api repos/o/r/pulls'",
    "gh alias set pc 'api -H \"X-HTTP-Method-Override: POST\" repos/o/r/issues'", "gh alias set pc 'api repos/o/r/pulls; pr view'",
    "gh alias set pc 'api \"repos/o/r/pulls'",
)
ALIAS_ALLOWED = ("gh alias set pv 'pr view'", "gh alias set --shell pv '!gh pr list | head'", "gh alias list", "gh alias set --help",
                 "gh alias set me 'api user --jq .login'", "gh alias set iss 'api repos/o/r/issues -H \"Accept: application/json\"'")
ALIAS_IMPORT_DENIED = ("gh alias import aliases.yml", "gh alias import -", "gh alias import --clobber aliases.yml", "gh -R o/r alias import f", "gh alias --help import f")


class PrSpellingTest(GateTestCase):
    def test_every_spelling_is_denied_without_a_record(self):
        self.start_branch("feature", "feat: a")
        for command in SPELLINGS:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no record")

    def test_every_spelling_is_denied_as_a_wrapped_form(self):
        for command in SPELLINGS:
            with self.subTest(command=command):
                self.assert_denied(self.gate(f"bash -c {shlex.quote(command)}"), "unchecked command form: run gh pr create as a plain command")

    def test_every_spelling_is_denied_in_a_substitution(self):
        self.start_branch("feature", "feat: a")
        for command in SPELLINGS:
            for wrapped in (f"echo $({command})", f"echo `{command}`"):
                with self.subTest(command=wrapped):
                    self.assertIsNotNone(self.denial(self.gate(wrapped)))

    def test_every_spelling_is_denied_when_the_command_cannot_be_parsed(self):
        for command in SPELLINGS:
            with self.subTest(command=command):
                self.assert_denied(self.gate(f'{command} "open'), "no branch to check: the command cannot be parsed")

    def test_every_spelling_is_allowed_with_a_passing_record(self):
        self.audited_branch()
        for command in SPELLINGS:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_options_after_the_command_words_are_still_read(self):
        self.audited_branch()
        self.assert_denied(self.gate("gh -R o/r pr create --base other"), "base mismatch")
        self.assert_denied(self.gate("gh pr -R o/r create --head nowhere"), "push first")

    def test_a_redirection_in_front_is_no_help_only_command(self):
        # The old gate denied these (an unchecked form); the help exemption must not allow them.
        self.start_branch("feature", "feat: a")
        for command in ("2>/dev/null gh pr create --help", ">out gh pr create -h", "gh >out pr create --help", "/usr/bin/gh 2>/dev/null pr new -h"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no record")

    def test_a_command_that_is_no_pr_create_is_allowed(self):
        for command in ("gh -R o/r pr list", "gh pr -R o/r view 1", "gh -R o/r pr create --help", "gh pr new -h", "gh pr status", "gh -R o/r issue create"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))


class ApiTest(GateTestCase):
    def test_a_call_that_opens_a_pull_request_is_denied(self):
        for command in API_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "gh api that opens a pull request is denied")

    def test_a_call_that_opens_a_pull_request_is_denied_when_wrapped(self):
        for command in API_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.gate(f"bash -c {shlex.quote(command)}"), "unchecked command form: run gh api pulls as a plain command")

    def test_a_read_only_call_and_another_write_are_allowed(self):
        for command in API_ALLOWED:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))


class ApiOverrideTest(GateTestCase):
    def test_a_call_with_a_method_override_header_is_denied(self):
        for command in OVERRIDE_DENIED:
            with self.subTest(command=command):
                self.assertIn("gh api", self.denial(self.gate(command)) or "")

    def test_a_call_with_the_header_only_is_denied_with_the_override_reason(self):
        for command in OVERRIDE_DENIED:
            if "pulls" not in command:
                with self.subTest(command=command):
                    self.assert_denied(self.gate(command), "gh api with a method-override header is denied")
        self.assert_denied(self.gate(OVERRIDE_DENIED[0]), "gh api with a method-override header is denied")

    def test_a_call_with_the_header_is_denied_when_wrapped(self):
        for command in OVERRIDE_DENIED:
            with self.subTest(command=command):
                reason = self.denial(self.gate(f"bash -c {shlex.quote(command)}"))
                self.assertIsNotNone(reason)
                self.assertTrue(reason.startswith("unchecked command form: run gh api "), reason)

    def test_a_call_with_the_header_is_denied_in_a_substitution(self):
        for command in OVERRIDE_DENIED:
            for wrapped in (f"echo $({command})", f"echo `{command}`"):
                with self.subTest(command=wrapped):
                    self.assertIsNotNone(self.denial(self.gate(wrapped)))

    def test_a_call_with_the_header_is_denied_when_the_command_cannot_be_parsed(self):
        self.assert_denied(self.gate(f'{OVERRIDE_DENIED[2]} "open'), "unchecked command form: the command cannot be parsed")

    def test_another_header_is_allowed(self):
        for command in OVERRIDE_ALLOWED:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))


class ApiSpeedTest(GateTestCase):
    def test_many_calls_in_one_command_are_gated_in_linear_time(self):
        started = time.monotonic()
        reason = self.denial(self.gate("gh api user " * 3000))  # denied: a call with 300 characters that cannot be read
        self.assertLess(time.monotonic() - started, 10)
        self.assertIsNotNone(reason)

    def test_a_separator_character_inside_a_quote_does_not_hide_the_endpoint(self):
        for command in ("bash -c 'gh api -X POST -f t=\"a|b\" repos/o/r/pulls'", "bash -c 'gh api -f t=\"a;b\" -X POST repos/o/r/pulls'",
                        "gh api -X POST -f t='a;b' repos/o/r/pulls \"open"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.denial(self.gate(command)))

    def test_a_long_call_that_cannot_be_read_is_denied_when_wrapped(self):
        self.assert_denied(self.gate(f"bash -c 'gh api user --jq {'x' * 400}'"), "unchecked command form: run gh api pulls as a plain command")


class AliasTest(GateTestCase):
    def test_an_alias_that_runs_a_pull_request_create_is_denied(self):
        for command in ALIAS_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "gh alias set with an expansion that opens a pull request")

    def test_an_alias_set_is_denied_when_wrapped(self):
        for command in ALIAS_DENIED + ALIAS_ALLOWED[:1]:  # the expansions with the PR words get the PR reason first
            with self.subTest(command=command):
                self.assertIsNotNone(self.denial(self.gate(f"bash -c {shlex.quote(command)}")))
        self.assert_denied(self.gate(f"bash -c {shlex.quote(ALIAS_ALLOWED[0])}"), "unchecked command form: run gh alias set as a plain command")

    def test_another_alias_is_allowed(self):
        for command in ALIAS_ALLOWED:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))


class AliasImportTest(GateTestCase):
    def test_an_alias_import_is_denied(self):
        for command in ALIAS_IMPORT_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "gh alias import is denied")

    def test_an_alias_import_is_denied_when_wrapped_or_in_a_substitution(self):
        for command in ALIAS_IMPORT_DENIED:
            with self.subTest(command=command):
                self.assert_denied(self.gate(f"bash -c {shlex.quote(command)}"), "unchecked command form: run gh alias import as a plain command")
                for wrapped in (f"echo $({command})", f"echo `{command}`"):
                    self.assertIsNotNone(self.denial(self.gate(wrapped)))

    def test_an_alias_import_is_denied_when_the_command_cannot_be_parsed(self):
        self.assert_denied(self.gate('gh alias import f "open'), "gh alias import is denied: the command cannot be parsed")

    def test_the_other_alias_commands_are_allowed(self):
        for command in ("gh alias list", "gh alias delete pc", "gh alias --help", "gh alias set --help"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))


class DispatchFlagTest(DispatchGateCase):
    SPELLINGS = (
        "orca orchestration --json worker-start --spec x --agent claude", "orca --json orchestration worker-start --spec x",
        "orca --environment e orchestration --json worker-start --spec x", "orca --pairing-code c orchestration worker-start --spec x",
        "orca-dev --json orchestration worker-start --spec x", "orca orchestration --task t worker-start", "orca orchestration --run r --agent claude worker-start",
        "orca --task t orchestration --spec x worker-start --agent claude", "/usr/bin/orca -- orchestration worker-start --spec x",
    )

    def test_every_spelling_is_denied_without_a_record(self):
        for command in self.SPELLINGS:
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record")

    def test_every_spelling_is_denied_as_a_wrapped_form(self):
        for command in self.SPELLINGS:
            with self.subTest(command=command):
                self.assert_denied(self.gate(f"bash -c {shlex.quote(command)}"), "unchecked command form: run orchestration worker-start as a plain command")

    def test_every_spelling_is_allowed_with_a_passing_record(self):
        self.pd_record()
        for command in self.SPELLINGS:
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_plain_exemptions_and_other_orchestration_commands_stay_allowed(self):
        for command in ("orca --json orchestration send --to t", "orca orchestration worker-start --retry-of t1", "orca orchestration worker-start -h"):
            with self.subTest(command=command):
                self.assert_allowed(self.gate(command))

    def test_the_exemptions_are_for_the_plain_form_only(self):
        # The old gate denied these (an unchecked form); an exemption must not allow them.
        for command in ("orca --json orchestration worker-start --retry-of t1", "orca --json orchestration worker-start --retry-of=t1",
                        "orca --json orchestration worker-start --help", "orca --environment e orchestration worker-start -h",
                        "orca orchestration --json worker-start --retry-of t1", "orca --environment e orchestration worker-start --retry-of t1"):
            with self.subTest(command=command):
                self.assert_denied(self.gate(command), "no pre-dispatch record")

    def test_a_lone_worker_start_word_in_a_command_that_cannot_be_parsed_is_denied(self):
        self.assert_denied(self.gate('$ORCA $SUB worker-start "open'), "no pre-dispatch record: the command cannot be parsed")


if __name__ == "__main__":
    unittest.main()
