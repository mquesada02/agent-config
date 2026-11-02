import json
import unittest

from redact_testkit import redact, run_post, bash_event, updated_output

FAKE = "FAKE_SECRET_123"


class KeyedFormatTest(unittest.TestCase):
    """Rules with a key name. Each test fails when its rule is removed (mutation-proven)."""

    def test_json_environment_secret_key_and_key_id(self):
        text = (
            '{"Variables": {"AWS_SECRET_ACCESS_KEY": "FAKE_SECRET_123", '
            '"AWS_ACCESS_KEY_ID": "FAKE_KEY_ID_456", "REGION": "us-east-1"}}'
        )
        expected = (
            '{"Variables": {"AWS_SECRET_ACCESS_KEY": "***", '
            '"AWS_ACCESS_KEY_ID": "***", "REGION": "us-east-1"}}'
        )
        self.assertEqual(redact(text), expected)
        json.loads(redact(text))

    def test_env_line(self):
        self.assertEqual(redact("DB_PASSWORD=FAKE_SECRET_123\nHOME=/home/x\n"), "DB_PASSWORD=***\nHOME=/home/x\n")

    def test_export_env_line(self):
        self.assertEqual(redact("export API_TOKEN=FAKE_SECRET_123\n"), "export API_TOKEN=***\n")

    def test_env_pair_anywhere_in_a_line(self):
        self.assertEqual(redact("FOO=1 TOKEN=abc cmd"), "FOO=1 TOKEN=***")
        self.assertEqual(redact("run --password=FAKE_SECRET_123 now"), "run --password=***")

    def test_yaml_password_line(self):
        self.assertEqual(redact("password: FAKE_SECRET_123\nname: web\n"), "password: ***\nname: web\n")

    def test_json_escaped_quotes(self):
        text = '{"msg": "{\\"password\\": \\"FAKE_SECRET_123\\"}"}'
        out = redact(text)
        self.assertEqual(out, '{"msg": "{\\"password\\": \\"***\\"}"}')
        self.assertEqual(json.loads(json.loads(out)["msg"]), {"password": "***"})

    def test_camel_case_and_hyphen_keys(self):
        self.assertEqual(redact('{"apiKey": "FAKE_SECRET_123"}'), '{"apiKey": "***"}')
        self.assertEqual(redact('{"AccessKeyId": "FAKE_SECRET_123"}'), '{"AccessKeyId": "***"}')
        self.assertEqual(redact('{"privateKey": "FAKE_SECRET_123"}'), '{"privateKey": "***"}')
        self.assertEqual(redact("x-api-key: FAKE_SECRET_123\n"), "x-api-key: ***\n")

    def test_key_names_substring_list(self):
        for key in ("GITHUB_TOKEN", "DB_PASSWD", "client_secret", "AWS_CREDENTIAL", "PRIVATE_KEY"):
            with self.subTest(key=key):
                self.assertEqual(redact(f"{key}=FAKE_SECRET_123"), f"{key}=***")


class ShapeTest(unittest.TestCase):
    """Rules with no key name."""

    def test_aws_key_id_in_text_output(self):
        self.assertEqual(redact("AKIAFAKEFAKEFAKE1234\n"), "***\n")
        self.assertEqual(redact("id ASIAFAKEFAKEFAKE1234 end"), "id *** end")

    def test_pem_block(self):
        text = "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIFAKEFAKE\nFAKEFAKE==\n-----END RSA PRIVATE KEY-----\nafter\n"
        self.assertEqual(redact(text), "before\n***\nafter\n")

    def test_jwt(self):
        self.assertEqual(
            redact("tok eyJhbGciOiJub25lIn0.eyJzdWIiOiJmYWtlIn0.ZmFrZXNpZw done"), "tok *** done"
        )

    def test_url_password_keeps_user_and_host(self):
        self.assertEqual(
            redact("postgres://app:FAKE_SECRET_123@db.example.com:5432/main"),
            "postgres://app:***@db.example.com:5432/main",
        )

    def test_vendor_github_ghp(self):
        self.assertEqual(redact("a ghp_FAKEFAKEFAKE1234_x-y b"), "a *** b")

    def test_vendor_github_gho(self):
        self.assertEqual(redact("a gho_FAKEFAKEFAKE1234 b"), "a *** b")

    def test_vendor_github_ghs(self):
        self.assertEqual(redact("a ghs_FAKEFAKEFAKE1234 b"), "a *** b")

    def test_vendor_github_pat(self):
        self.assertEqual(redact("a github_pat_FAKEFAKEFAKE1234 b"), "a *** b")

    def test_vendor_anthropic(self):
        self.assertEqual(redact("a sk-ant-fakefake-FAKE1234 b"), "a *** b")

    def test_vendor_slack(self):
        for letter in "abprs":
            with self.subTest(letter=letter):
                self.assertEqual(redact(f"a xox{letter}-FAKE-1234 b"), "a *** b")

    def test_keyed_formats_run_before_shapes(self):
        self.assertEqual(redact("API_KEY=postgres://u:p@h"), "API_KEY=***")


class UnchangedTest(unittest.TestCase):
    def assert_unchanged(self, text):
        result = run_post(bash_event(text))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_no_secret_gives_empty_stdout(self):
        self.assert_unchanged("total 4\ndrwxr-xr-x 2 user user 4096 Nov 2 .\nhello world\n")

    def test_key_names_alone_stay(self):
        self.assert_unchanged('[\n  "AWS_SECRET_ACCESS_KEY",\n  "DB_PASSWORD"\n]\n')
        self.assert_unchanged("AWS_SECRET_ACCESS_KEY\nDB_PASSWORD\n")

    def test_value_guard_values_stay(self):
        for text in (
            "max_tokens: 4096\n",
            "TOKEN_TTL=3600\n",
            '{"TOKEN": "3600"}',
            '{"TOKEN": 3600}',
            "secret: true\n",
            "SECRET=False\n",
            "password: null\n",
            "password:\n",
            "PASSWORD=\n",
            'PASSWORD=""\n',
            '{"Token": 1.5, "secret": -3, "x_token": "+2.25", "y_token": ""}',
            '{"secret": {}, "token": []}',
        ):
            with self.subTest(text=text):
                self.assert_unchanged(text)


class ValueExtentTest(unittest.TestCase):
    def test_quoted_env_value_with_spaces(self):
        self.assertEqual(redact('PASSWORD="a b c"\n'), 'PASSWORD="***"\n')
        self.assertEqual(redact("PASSWORD='a b c' tail\n"), "PASSWORD='***' tail\n")

    def test_env_escaped_quote_is_part_of_the_value(self):
        self.assertEqual(redact('PASSWORD="a\\"b c" tail\n'), 'PASSWORD="***" tail\n')

    def test_env_quote_with_no_closing_quote_runs_to_end_of_line(self):
        self.assertEqual(redact('PASSWORD="abc def\nnext=1\n'), 'PASSWORD="***"\nnext=1\n')

    def test_env_unquoted_value_runs_to_end_of_line(self):
        self.assertEqual(redact("TOKEN=abc def ghi\nnext=1\n"), "TOKEN=***\nnext=1\n")

    def test_yaml_unquoted_value_with_spaces(self):
        self.assertEqual(redact("password: a b c\nnext: 1\n"), "password: ***\nnext: 1\n")

    def test_yaml_quoted_value_runs_to_closing_quote(self):
        self.assertEqual(redact('password: "a b" # note\n'), 'password: "***" # note\n')

    def test_yaml_block_scalar(self):
        text = "private_key: |\n  line1\n\n  line2\nother: 1\n"
        self.assertEqual(redact(text), "private_key: ***\nother: 1\n")
        self.assertEqual(redact("secret: >-\n    a\n    b\nnext: 2\n"), "secret: ***\nnext: 2\n")

    def test_yaml_block_scalar_in_a_list_item_and_nested(self):
        text = "items:\n  - token: |\n      aaa\n    name: x\n"
        self.assertEqual(redact(text), "items:\n  - token: ***\n    name: x\n")

    def test_json_object_under_matched_key_becomes_one_value(self):
        text = '{"credentials": {"user": "u", "pw": "p"}, "x": 1}'
        self.assertEqual(redact(text), '{"credentials": "***", "x": 1}')
        self.assertEqual(redact('{"token": ["a", "b"], "x": 1}'), '{"token": "***", "x": 1}')

    def test_json_object_brackets_inside_strings_are_ignored(self):
        text = '{"secret": {"a": "}", "b": 2}, "z": 1}'
        self.assertEqual(redact(text), '{"secret": "***", "z": 1}')

    def test_json_object_with_no_closing_bracket(self):
        self.assertEqual(redact('{"secret": {"a": "b", "c": "d"'), '{"secret": "***"')

    def test_pem_begin_line_with_no_end_line(self):
        text = "head\n-----BEGIN PRIVATE KEY-----\nMIIFAKEFAKE\nFAKE\n"
        self.assertEqual(redact(text), "head\n***")

    def test_line_that_matches_json_and_yaml_uses_the_json_extent(self):
        self.assertEqual(redact('"password": "abc",\n'), '"password": "***",\n')

    def test_json_escaped_value_with_quote_inside(self):
        self.assertEqual(redact('{"password": "a\\"b"}'), '{"password": "***"}')

    def test_pem_inside_an_env_value_is_hidden_whole(self):
        text = "PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\nMIIFAKE\n-----END PRIVATE KEY-----\nnext=1\n"
        out = redact(text)
        self.assertNotIn("MIIFAKE", out)
        self.assertIn("next=1", out)


class ShapeKeepingTest(unittest.TestCase):
    def test_bash_stdout_and_stderr_are_redacted_and_keys_kept(self):
        event = bash_event("a PASSWORD=FAKE_SECRET_123\n", "err TOKEN=FAKE_SECRET_123\n")
        event["tool_response"]["interrupted"] = True
        out = updated_output(run_post(event))
        self.assertEqual(
            out,
            {
                "stdout": "a PASSWORD=***\n",
                "stderr": "err TOKEN=***\n",
                "interrupted": True,
                "isImage": False,
                "noOutputExpected": False,
            },
        )

    def test_read_shape_keeps_its_keys(self):
        response = {
            "type": "text",
            "file": {
                "filePath": "/work/.env",
                "content": "API_KEY=FAKE_SECRET_123\nok=1\n",
                "numLines": 3,
                "startLine": 1,
                "totalLines": 3,
            },
        }
        event = {"tool_name": "Read", "tool_response": response}
        out = updated_output(run_post(event))
        expected = json.loads(json.dumps(response))
        expected["file"]["content"] = "API_KEY=***\nok=1\n"
        self.assertEqual(out, expected)

    def test_grep_content_shape_keeps_its_keys(self):
        response = {
            "mode": "content",
            "numFiles": 0,
            "filenames": [],
            "content": "secret.txt:2:API_TOKEN=FAKE_SECRET_123",
            "numLines": 1,
            "totalLines": 1,
        }
        out = updated_output(run_post({"tool_name": "Grep", "tool_response": response}))
        self.assertEqual(out, dict(response, content="secret.txt:2:API_TOKEN=***"))

    def test_grep_count_shape_keeps_its_keys(self):
        response = {"mode": "count", "numFiles": 1, "filenames": [], "content": "a.env:PASSWORD=FAKE_SECRET_123", "numMatches": 1}
        out = updated_output(run_post({"tool_name": "Grep", "tool_response": response}))
        self.assertEqual(out, dict(response, content="a.env:PASSWORD=***"))

    def test_grep_files_with_matches_shape_without_secret_prints_nothing(self):
        response = {"mode": "files_with_matches", "filenames": ["secret.txt"], "numFiles": 1, "totalFiles": 1}
        result = run_post({"tool_name": "Grep", "tool_response": response})
        self.assertEqual(result.stdout, "")

    def test_nested_lists_and_unknown_read_type_are_walked(self):
        response = {"type": "other", "items": ["x", {"note": "TOKEN=FAKE_SECRET_123"}], "count": 2}
        out = updated_output(run_post({"tool_name": "Read", "tool_response": response}))
        self.assertEqual(out, {"type": "other", "items": ["x", {"note": "TOKEN=***"}], "count": 2})

    def test_redacted_json_output_still_parses(self):
        text = json.dumps({"Variables": {"DB_PASSWORD": "FAKE_SECRET_123", "N": 1}}, indent=2)
        self.assertEqual(json.loads(redact(text)), {"Variables": {"DB_PASSWORD": "***", "N": 1}})


if __name__ == "__main__":
    unittest.main()
