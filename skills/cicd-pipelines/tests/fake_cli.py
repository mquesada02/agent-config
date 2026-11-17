"""Fake `aws`, `gh`, `curl` and `terraform` executables for the template script tests (a helper module, not a test file).

Each fake logs one line for each call (the tool name and its arguments) to a file, and answers from
environment variables. They are bash scripts in front of the real PATH, so the real `bash`,
`sha256sum` and `sleep` run. No test reaches a network, a cloud, GitHub or a container.
"""
import hashlib
import os
import subprocess
import tempfile

from skill_files import SKILL

SCRIPTS = os.path.join(SKILL, "templates", "scripts")

# `aws s3 cp s3://bucket/sha/<file> <dest>` copies the prepared file of the store. `aws lambda publish-version`
# prints a version number. `curl` prints FAKE_BODY, and fails when FAKE_CURL_FAIL is set. The fake `gh` prints the
# deployment ids of FAKE_DEPLOY_IDS for the deployments call and FAKE_STATE for each statuses call.
FAKES = {
    "aws": """#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
if [ "$1 $2" = "s3 cp" ]; then cp "$FAKE_STORE/$(basename "$3")" "$4"; fi
if [ "$1 $2" = "lambda publish-version" ]; then echo 7; fi
""",
    "curl": """#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
if [ -n "${FAKE_CURL_FAIL:-}" ]; then exit 22; fi
printf '%s' "${FAKE_BODY:-}"
""",
    "terraform": """#!/usr/bin/env bash
echo "terraform $*" >> "$FAKE_LOG"
""",
    "gh": """#!/usr/bin/env bash
echo "gh $*" >> "$FAKE_LOG"
case "$2" in
  *statuses*) echo "${FAKE_STATE:-}" ;;
  *deployments*) printf '%s\\n' ${FAKE_DEPLOY_IDS:-} ;;
esac
""",
}
SHA = "0123456789abcdef0123456789abcdef01234567"
ZIP = b"synthetic zip bytes"


def trash(path):
    """Move a folder to /tmp/cd-scripts-trash (the repo rule: never a recursive delete)."""
    folder = os.path.join(tempfile.gettempdir(), "cd-scripts-trash")
    os.makedirs(folder, exist_ok=True)
    os.rename(path, os.path.join(folder, os.path.basename(path)))


class Run:
    """One run of a template script: exit code, output and the logged tool calls."""

    def __init__(self, done, log):
        self.code, self.out, self.err = done.returncode, done.stdout, done.stderr
        with open(log, encoding="utf-8") as handle:
            self.calls = handle.read().splitlines()

    def called(self, text):
        return [call for call in self.calls if text in call]


class Sandbox:
    def __init__(self, test):
        self.dir = tempfile.mkdtemp(prefix="cd-scripts-")
        test.addCleanup(trash, self.dir)
        self.bin = os.path.join(self.dir, "bin")
        self.store = os.path.join(self.dir, "store")
        self.work = os.path.join(self.dir, "work")
        for folder in (self.bin, self.store, self.work):
            os.mkdir(folder)
        self.log = os.path.join(self.dir, "calls.log")
        open(self.log, "w", encoding="utf-8").close()
        for name, text in FAKES.items():
            path = os.path.join(self.bin, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(path, 0o755)
        self.store_artifact()

    def store_artifact(self, zip_bytes=ZIP, digest=None):
        """Put app.zip and app.zip.sha256 in the fake bucket. A digest other than the real one makes a changed zip."""
        digest = digest or hashlib.sha256(ZIP).hexdigest()
        with open(os.path.join(self.store, "app.zip"), "wb") as handle:
            handle.write(zip_bytes)
        with open(os.path.join(self.store, "app.zip.sha256"), "w", encoding="utf-8") as handle:
            handle.write(digest + "\n")

    def run(self, script, *args, **env):
        environment = {"PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_LOG": self.log,
                       "FAKE_STORE": self.store, "VERIFY_PAUSE": "0", "HOME": self.dir}
        environment.update(env)
        done = subprocess.run(["bash", os.path.join(SCRIPTS, script), *args], cwd=self.work, env=environment,
                              capture_output=True, text=True, timeout=60)
        return Run(done, self.log)
