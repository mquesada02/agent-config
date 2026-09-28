# Always use the following rules

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Prototyping

If you're unsure if something works, or you want to do a cheap test before providing a solution, use /mattpocock-skills:prototype

## 6. Code review

After implementing code, always run this review loop:

Issue types:
- **Blocking**: bugs, logic errors, missing cases, spec mismatches.
- **Minor**: cosmetic, naming, style, judgement calls.

The main session decides the final type. A spec mismatch is always blocking, whatever the reviewer called it.

1. **Correctness phase.** Run /mattpocock-skills:code-review. Verify each blocking fix doesn't introduce new bugs (see section 3), apply it, and re-run. Record minor issues but don't fix them yet. Done after two consecutive rounds with no blocking issues.
2. **Quality phase.** Apply the recorded minor issues, then run /simplify. Repeat /simplify until it makes no more changes.
3. **Final phase.** Run /mattpocock-skills:code-review until two consecutive rounds have no blocking issues. A blocking issue here means: fix it, then go back to step 2. A comment-only or wording change does not restart the count, and minor findings are listed for the user instead of fixed.
4. If you're unsure of anything, ask the user.

## 7. General workflow for any task

**Note**: _grilling_ refers to the /mattpocock-skills:grilling skill, already included in the /mattpocock-skills:wayfinder skill.

**Exception:** for small tasks (estimated under ~50 changed lines), skip steps 1–5: implement directly, then run the section 6 review loop.

When implementing any task, you must do these steps in the corresponding order:

1. /mattpocock-skills:wayfinder to create a general map for the task.
2. /mattpocock-skills:to-spec after grilling the user, for the general spec.
3. Review the spec with subagents using the axes from /mattpocock-skills:code-review. Use only the correctness phase of section 6, then apply the recorded minor issues.
4. /mattpocock-skills:to-tickets after creating the general spec.
5. For each one of the created tickets, dispatch an Orca worker (see section 11) that executes each of these steps:
5.1. run /mattpocock-skills:wayfinder to get an overview of the map, grilling the user again if needed.
5.2. run /mattpocock-skills:to-spec to generate a specialized spec of that ticket.
5.3. Review the spec with subagents using the axes from /mattpocock-skills:code-review. Use only the correctness phase of section 6, then apply the recorded minor issues.
5.4. After the spec comes out clean, run /mattpocock-skills:implement to implement the spec. Do not go off-topic of the spec; you only have to implement it on this step.
5.5. Review the implementation of the spec with subagents using the axes from /mattpocock-skills:code-review. Use the same logic described on section 6 of this document.

After starting step 5, the original session acts as a **coordinator** of the Orca workers it dispatched.
These steps are mandatory.
If any of the Orca workers needs grilling, it must escalate the grilling session to the coordinator, and the coordinator must send the answers back to that worker.

## 8. Git contribution

Never add Claude Code attribution to commits, PRs or comments. The `attribution` setting already blanks it; remove any that still appears.
When committing code, you must use the /smart-commits skill.
When merging a PR, follow these rules:
- if **base** is `develop` or `main`, you must squash-merge the PR
- if not, create a merge commit 

After merging: delete the remote branch, remove the worktree (section 10), then in the main checkout switch to the **base** branch, pull, and delete the local branch.

## 9. Model selection

When spawning subagents or Orca workers, make sure to use Sonnet models for token reduction. For Orca workers, the /orca-cli skill explains how to set the model.

## 10. Worktrees

Always work inside a git worktree, for every task, including one-line fixes and non-code changes. Never work directly in the main checkout.
- Create worktrees with /orca-cli, in Orca's configured workspace folder. If Orca isn't running or the repo isn't managed by Orca, stop and ask the user.
- Every Orca ticket worker gets its own child worktree.
- Outside a git repository, skip worktrees and work in place.
- Exception: config repositories (`~/.claude`, dotfiles): edit in place, no worktree.
- After the branch is merged, delete the worktree before deleting the local branch (see section 8).

## 11. Task delegation

- Use built-in subagents (Agent tool) ONLY for /mattpocock-skills:code-review runs. That includes the reviews in section 7, steps 3, 5.3 and 5.5.
- Skills that start their own subagents (for example /mattpocock-skills:research or /simplify) may do so. This rule covers subagents you spawn yourself.
- Use Orca for all other delegation:
  - /orchestration: coordinating workers and waiting for results (task DAGs, ask/reply, worker_done, escalations). The section 7 coordinator uses this.
  - /orca-cli: full handoffs, spawning agents in child worktrees, reading or sending to terminals.
- Outside a git repository, ask the user before delegating to Orca workers.

## 12. No polling

Do not poll with filler commands like `echo`, `true`, or `sleep` loops.
If you spawned a background shell, Monitor, subagent, or Orca worker, you will be notified when it finishes. Wait for that notification.
Blocking Orca CLI wait commands are allowed. They are not polling.
A notification with nothing new needs only a text reply, not a tool call.

## 13. Deleting files

Never use `rm -rf` or other recursive deletes. To remove something:
- If it may be needed again, move it to a dated backup folder (`<dir>-backup-YYYY-MM-DD/`) and tell the user the path.
- If it must go, move it to `/tmp`, which the system clears, or give the user the command to delete it manually.
