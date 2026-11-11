#!/usr/bin/env python3
"""Check that each SHA-pinned `uses:` line of a repo points to a real commit (SEC-01).

Usage: check_pins.py REPO_PATH

Standard library only, plus `gh` as a subprocess. Every `gh` call is a read-only `gh api <path>` call, one
lookup for each distinct repo and tag. Prints one JSON object: {"status", "unverified_reasons", "pins"}.
Each pin has "file", "line", "uses", "sha", "tag" and a "result": ok, tag-mismatch (the version comment tag
is another commit), unknown-tag (the tag does not exist), unknown-commit (the SHA is not a commit of the
repo) or unverified (with a "reason": gh-missing, not-logged-in, no-network, rate-limited, repo-unreadable
or gh-error). The status is "unverified" when a pin is unverified. A pin that could not be checked is
never a finding. The script exits 0 for every result, and 2 on a usage error.
"""
import glob
import json
import os
import re
import subprocess
import sys

PIN = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([\w.-]+/[\w.-]+)((?:/[^@\s'\"]+)?)@([0-9a-f]{40})['\"]?"
                 r"(?:\s+#\s*([\w./-]+))?")
ERRORS = ((("http 404", "no commit found"), "not-found"), (("rate limit", "http 429"), "rate-limited"),
          (("gh auth login", "http 401", "not logged"), "not-logged-in"),
          (("error connecting", "could not resolve", "dial tcp"), "no-network"))


class Unavailable(Exception):
    """gh could not answer: the exception text is the reason."""


def get(path):
    """The parsed JSON of `gh api <path>`, or None when the answer is "not found".

    That is HTTP 404, or the HTTP 422 "No commit found" of a SHA that is not in the repo.
    Any other failure raises Unavailable.
    """
    try:
        done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise Unavailable("gh-missing")
    except subprocess.TimeoutExpired:
        raise Unavailable("no-network")
    except (OSError, UnicodeDecodeError):
        raise Unavailable("gh-error")
    if done.returncode == 0:
        try:
            return json.loads(done.stdout)
        except ValueError:
            raise Unavailable("gh-error")
    error = done.stderr.lower()
    reason = next((name for words, name in ERRORS if any(word in error for word in words)), "gh-error")
    if reason == "not-found":
        return None
    raise Unavailable(reason)


def tag_commit(repo, tag):
    """The commit SHA of a tag (an annotated tag is dereferenced), or None when the tag does not exist."""
    try:
        ref = get(f"repos/{repo}/git/ref/tags/{tag}")
        obj = ref["object"] if ref else None
        while obj and obj["type"] == "tag":
            annotated = get(f"repos/{repo}/git/tags/{obj['sha']}")
            obj = annotated["object"] if annotated else None
        return obj["sha"] if obj else None
    except (KeyError, TypeError):
        raise Unavailable("gh-error")


def verify(repo, sha, tag, cache):
    """(result, reason) of one pin."""
    if repo not in cache:
        cache[repo] = get(f"repos/{repo}") is not None
    if not cache[repo]:
        return "unverified", "repo-unreadable"
    found = None
    if tag:
        if (repo, tag) not in cache:
            cache[(repo, tag)] = tag_commit(repo, tag)
        found = cache[(repo, tag)]
    if found == sha:
        return "ok", None
    if (repo, sha) not in cache:
        cache[(repo, sha)] = get(f"repos/{repo}/commits/{sha}") is not None
    if not cache[(repo, sha)]:
        return "unknown-commit", None
    if not tag:
        return "ok", None
    return ("tag-mismatch" if found else "unknown-tag"), None


def find_pins(repo):
    """Every SHA-pinned `uses:` line of the workflow files of a repo, as pin dicts without a result."""
    pins = []
    for path in sorted(glob.glob(os.path.join(repo, ".github", "workflows", "*.y*ml"))):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                found = PIN.match(line)
                if found:
                    name, sub, sha, tag = found.groups()
                    pins.append({"file": os.path.relpath(path, repo), "line": number, "uses": name + sub,
                                 "sha": sha, "tag": tag})
    return pins


def main(argv):
    if len(argv) != 2 or not os.path.isdir(argv[1]):
        print("usage: check_pins.py REPO_PATH", file=sys.stderr)
        return 2
    pins, cache, stopped = find_pins(argv[1]), {}, None
    for pin in pins:
        reason = stopped
        if stopped:
            pin["result"] = "unverified"
        else:
            try:
                pin["result"], reason = verify("/".join(pin["uses"].split("/")[:2]), pin["sha"], pin["tag"], cache)
            except Unavailable as error:
                pin["result"], stopped = "unverified", str(error)
                reason = stopped
        if reason:
            pin["reason"] = reason
    reasons = sorted({pin["reason"] for pin in pins if "reason" in pin})
    print(json.dumps({"status": "unverified" if reasons else "verified", "unverified_reasons": reasons,
                      "pins": pins}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
