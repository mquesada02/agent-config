#!/usr/bin/env python3
# PreToolUse hook on the Skill tool: denies each built-in skill that runs forked, in every session.
# A forked skill starts its subagent on the parent session's model, not on Sonnet. The audit (S7) reads every session
# that touches an audited worktree, so one forked skill in a session fails S7 for every worktree that the session
# touches, and the transcript can never be cleaned. A session cannot know in advance which worktrees an audit will
# read, so the hook has no registry lookup. Exit 2 blocks the call and shows the reason to the agent.
import json
import sys

# The one list of forked built-in skills. How it was found (Claude Code 2.1.322, 2026-11-10):
# - Evidence: /code-review forked a subagent on claude-opus-5-5 (issue 241, audit of map 233, S7 failure).
# - Claude Code marks a forked skill with `context: "fork"` (frontmatter or built-in definition). Searching the
#   binary for that flag finds no other bundled skill that the model can call. The only other hits are the internal
#   claude-test skills "execute" and "draft", which are not user-invocable.
# Add a skill here when a new Claude Code release forks another built-in skill.
FORKED_BUILTIN_SKILLS = ("code-review",)


def block(reason: str) -> None:
    print(f"Blocked by ~/.claude/hooks/forked-skills/block_forked_skills.py: {reason}", file=sys.stderr)
    sys.exit(2)


def main() -> None:
    try:
        skill = json.load(sys.stdin)["tool_input"]["skill"]
    except (ValueError, KeyError, TypeError):
        skill = None
    if not isinstance(skill, str):
        block("the hook cannot read the skill name, so it cannot check whether the skill runs forked.")
    name = skill.strip().lstrip("/").strip()
    if name in FORKED_BUILTIN_SKILLS:
        block(
            f"the built-in skill '{name}' runs forked. "
            "Its forked subagent would run on the parent session's model, not on Sonnet, and would fail the audit "
            "check S7 for every worktree that this session touches. Run it in a separate session that touches no "
            "audited worktree."
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
