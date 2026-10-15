# Do user-run `!` commands skip PreToolUse hooks?

Ticket: mquesada02/agent-config#83. Researched 2026-10-15, Claude Code 2.1.300.

## Answer

Very likely yes: `!` (shell mode) commands do not go through the agentic loop, so PreToolUse and PostToolUse `Bash` hooks do not fire for them, and the user can override a `gh pr create` block by typing `! gh pr create`. The docs never state this in one sentence; it follows from (a) the hooks docs defining PreToolUse/PostToolUse as firing on tool calls inside the agentic loop, (b) the interactive-mode docs saying shell mode runs "directly without going through Claude" and "Doesn't require Claude to interpret or approve the command", and (c) the local transcript, where the `!` command is stored as a plain user message with no tool_use, no `toolUseID` and no hook attachment. In the transcript the command appears as `<bash-input>` and its output as `<bash-stdout>`/`<bash-stderr>` user messages. Confidence: medium-high (about 85%). Not proven by an explicit doc sentence or a logging-hook test; the test below closes that gap.

## Evidence

1. Hooks doc, scope of PreToolUse/PostToolUse. Source: https://code.claude.com/docs/en/hooks (lifecycle section). Quote: "on every tool call inside the agentic loop: `PreToolUse` and `PostToolUse`, except `EndConversation` calls, which skip both". Event table: "`PreToolUse` | Before a tool call executes. Can block it"; "`PostToolUse` | After a tool call succeeds". The only listed exception is EndConversation; `!` commands are not mentioned anywhere in the page (searched the full raw page for `!`, "bash mode", "shell mode", "user-typed").
2. Hooks doc, user-typed input has its own events. Source: https://code.claude.com/docs/en/hooks event table. Quotes: "`UserPromptSubmit` | When a prompt is submitted, before Claude processes it"; "`UserPromptExpansion` | When a user-typed command expands into a prompt, before it reaches Claude. Can block the expansion". Whether UserPromptSubmit fires for a `!` command is not documented.
3. Interactive-mode doc. Source: https://code.claude.com/docs/en/interactive-mode (section "Shell mode with `!` prefix"). Quotes: "Run shell commands directly without going through Claude by prefixing your input with `!`"; "Adds the command and its output to the conversation context"; "Doesn't require Claude to interpret or approve the command". Also: "commands you type in shell mode run outside the sandbox even when you've enabled sandboxing, because the sandbox applies to the commands Claude runs." This shows shell mode is a separate execution path from Claude's Bash tool.
4. Local transcript, project `-home-mquesada--claude`, file `~/.claude/projects/-home-mquesada--claude/2e56c352-7ba9-4bb9-be6f-0c4a8e8d2699.jsonl`, lines 713-714 (2026-10-15T15:27:24Z, version 2.1.300). Two consecutive records, both `"type":"user"` with fields `parentUuid, isSidechain, promptId, type, message, uuid, timestamp, userType, entrypoint, cwd, sessionId, version, gitBranch` (the second adds `turnOrigin`, `turnPosition`):
   - Input: `message: {"role":"user","content":"<bash-input> gh pr merge 81 --squash --delete-branch</bash-input>"}`
   - Output: `message: {"role":"user","content":"<bash-stdout></bash-stdout><bash-stderr>...</bash-stderr>"}`, sharing the same `promptId`.
   - Neither record has `tool_use`/`tool_result` content, a `toolUseID`, or an `attachment`. Hook runs in the same file are separate `"attachment":{"type":"hook_success","hookName":...,"toolUseID":...,"hookEvent":"PreToolUse"|"PostToolUse"|...}` records (73 PreToolUse, 71 PostToolUse in this file); none sits between or after lines 713-714 for this command. Compare line 695: the same command run by the model is an assistant `tool_use` record (`name":"Bash"`), which is the shape PreToolUse hooks attach to.
   - Also an `api-request-blob` (line 716) shows the model receives the command as `<bash-input>` plus `<bash-stdout>`/`<bash-stderr>` text, i.e. it is context, not a tool call.
5. Context in the same transcript (line 709): the model's own `gh pr merge 81` Bash call was blocked by the auto-mode classifier, and the model told the user to type `! gh pr merge 81 ...`, after which it ran. This is consistent with `!` bypassing tool-call gating, but the classifier is a permission mechanism, not a PreToolUse hook, so it is weaker evidence for hooks specifically.

## Open gaps

- No doc sentence says "PreToolUse does not fire for `!` commands" (nor the reverse). The conclusion is inferred.
- Absence of hook records in the transcript is only indirect: a command-type hook that exits 0 with no output may leave no attachment record, so the transcript cannot prove a hook did not run. (Existing hooks in this repo do leave `hook_success` attachments for tool calls, which makes the absence suggestive, not conclusive.)
- Whether `UserPromptSubmit` fires for `!` input is undocumented and unverified. A `UserPromptSubmit` hook could be a way to gate `!` commands if one ever wants to; this repo has none configured.
- PostToolUse for `!` commands: same inference as PreToolUse (not a tool call), not directly tested.
- Behavior may differ across versions; only 2.1.300 was inspected.

## Proposed reproducible test

Run in a throwaway session; do not touch live settings. Use a scratch settings file loaded only for this test.

1. Create `/tmp/bang-test/settings.json`:
   ```json
   {"hooks":{
     "PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"cat >> /tmp/bang-test/log.txt; echo >> /tmp/bang-test/log.txt"}]}],
     "PostToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"cat >> /tmp/bang-test/log.txt; echo >> /tmp/bang-test/log.txt"}]}],
     "UserPromptSubmit":[{"hooks":[{"type":"command","command":"cat >> /tmp/bang-test/log.txt; echo >> /tmp/bang-test/log.txt"}]}]
   }}
   ```
2. Start `claude --settings /tmp/bang-test/settings.json` in a scratch directory.
3. Type `! echo BANG_TEST_1` and wait for the output.
4. Type `Run the shell command: echo MODEL_TEST_2` (the model uses the Bash tool; approve if prompted).
5. `grep -c BANG_TEST_1 /tmp/bang-test/log.txt` should be 0 if PreToolUse/PostToolUse skip `!` commands; `grep -c MODEL_TEST_2` should be at least 2 (Pre and Post). Entries with `"hook_event_name":"UserPromptSubmit"` containing `! echo BANG_TEST_1` answer the UserPromptSubmit question.
6. Delete `/tmp/bang-test` afterwards (move it, per the no-recursive-delete rule).
