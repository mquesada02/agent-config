# Always use the following rules

## 0. Priorities

Correctness comes before simplicity. Correctness means a sound design: no hidden coupling, no temporary fixes, and no weaker security.
- Sections 2 and 3 apply only between options that are equally correct. A root-cause fix may add code, add an abstraction, or touch lines outside the request.
- Never add a temporary fix or workaround without the user's approval. If approved, mark it in the code with a comment that says why it is temporary.
- When you recommend an option (for example with AskUserQuestion), recommend the most correct one, and state what it costs compared with the simpler one.
- Scope does not grow: "no features beyond what was asked" still applies.

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

After implementing code, always run this review loop. Every phase of the loop has a round cap, so the loop always ends.

The loop session is the session that runs this loop: the main session, or the worker in section 7 step 5.5.

Finding types:
- **Blocking**: a bug, a logic error, a missing case, a spec mismatch, weaker security, hidden coupling, or an unapproved temporary fix. Each Blocking finding needs its evidence:
  - A spec mismatch: the quoted spec line. A spec mismatch is always Blocking, whatever the reviewer called it.
  - Weaker security, hidden coupling or an unapproved temporary fix: these break section 0. Their evidence is the quoted code and the section 0 rule.
  - Any other Blocking finding: a concrete failure, that is, an input or state and the wrong result.
  A finding without its evidence is Minor. Ask the reviewers for this evidence in their brief.
- **Minor**: everything else (cosmetic, naming, style, smells, judgement calls).

The loop session decides the final type.

Roles. The agent that reports a finding never fixes it, so a second agent checks each finding first:
- **Reviewers** (the /mattpocock-skills:code-review subagents) report findings. They do not fix. They are read-only toward remote state: the hook `~/.claude/hooks/subagent-readonly/block_subagent_writes.py` denies their remote-write commands (`gh` writes, `git push`, `terraform apply`, `aws` writes). A reviewer that needs such a command reports the need as a finding.
- **Verifier**: one Sonnet subagent per Blocking finding. It confirms the failure from the code (a failing test, a traced path, or a quoted line), or it rejects the finding. The loop session marks a rejected finding as rejected in the ledger.
- **Fixer**: the loop session. For each confirmed Blocking finding:
  1. Write a test that reproduces it, where the change can be tested.
  2. List the callers and the tests that the fix can affect.
  3. Apply the smallest fix.
  4. Run the affected tests.

Ledger: the loop session keeps one findings ledger per task. It writes the ledger only through `python3 -I ~/.claude/hooks/workflow-audit/audit ledger <event> --worktree <path> ...` (the `audit ledger` command), which rejects a malformed event at once. The event kinds are:
- `round`: each review round, with its loop, phase, round number and reviewer agent ids. Each reviewer id is a subagent of the loop session; `audit ledger` refuses another id (exit 2, nothing written), so write the `round` event only after its reviewers ran.
- `finding`: each finding, with its id, `file:line`, type and a one-line reason. A Blocking finding of a plan-review loop needs `--quote` (the quoted line, which must be in the reason and in what that round's reviewers wrote; `audit ledger` refuses a finding without it). `--raised` marks a finding that the loop session raised to Blocking itself (section 7 step 3 (c), or a section 6 spec mismatch); it needs `--quote`, which comes from the map or the spec and is not matched against the reviewers.
- `finding-amend`: repairs the reason of an existing finding, with `--id`, `--reason`, `--quote` and `--raised`. It follows the same quote rule as `finding`, with the loop, phase and round of the original finding, and each amendment states its own `--raised` mark. The latest amendment is in force; the original and every amendment stay on the ledger. The type, loop, phase, round, location and status never change.
- `verdict`: the result of a verifier for a Blocking finding, with the verifier agent id.
- `status`: a finding becomes fixed, deferred or rejected. A finding is open until a `status` event closes it.
- `phase-commit`: the SHA of the commit made at the start of the quality phase.
- `extension`: the owner's approval of extra rounds of one loop phase, with the loop, the phase, the rounds (1 to 5) and the owner's own words as the quote.
- `size-approval`: the owner's approval of a larger diff on the small-task path (section 7 Exception), with the approved size as `--lines` and the user's own words as `--quote`. The session asks with AskUserQuestion, puts the approved line count in the question as a whole number, and records the chosen answer as the quote. S5 checks that the quote is in an AskUserQuestion answer at or before the event, to a question that names `--lines`, and that one answer backs one `size-approval`.
At a cap, the session that asked the user and got the approval writes the `extension` event (for a worker, the coordinator), with `--worktree` as an absolute path (never `~` or `$HOME`) and the owner's own words as the quote.
The loop session also keeps a copy of the entries in the scratchpad, and gives that copy to every reviewer. A finding that matches a ledger entry is not new. Reviewers do not report rejected or deferred entries again, unless they add new evidence.

1. **Correctness phase.** Run /mattpocock-skills:code-review. Confirm each Blocking finding with a verifier, then fix each confirmed one. Record the Minor findings in the ledger. Every round reviews the full diff. Reviewers report only findings that are new to the ledger. Done after one round with no new confirmed Blocking finding. Cap: 5 rounds.
2. **Quality phase (once).** Commit with /smart-commits first, so step 3 has a fixed point. Sort the open Minor findings into two groups:
   - Apply: a change in one file, with no behavior change and no public interface change.
   - Defer: every other Minor finding. Mark it deferred in the ledger.
   Apply the first group in one pass, then run the tests. If a test fails, revert the applied changes one at a time until the tests pass. Mark each reverted finding deferred, and each kept finding fixed. Then run /simplify once and run the tests again. Revert each /simplify change that breaks a test.
3. **Final phase.** Run one /mattpocock-skills:code-review round on the diff since the commit made at the start of step 2. Only confirmed Blocking findings fail a round. Mark each new Minor finding deferred. Confirm and fix each Blocking finding as in step 1, then repeat this step. Each repeat reviews the diff from that same commit, which now includes the fixes. If the base branch moves after the quality-phase commit, rebase, record the rebased commit with a new `phase-commit` event, and run one more final round when its patch-id differs. Done after one round with no confirmed Blocking finding. Cap: 3 rounds.
4. **Report.** List the deferred Minor findings for the user. Leave them unfixed in this task, because fixing them would reopen the review.
5. **Audit.** Before you tell the user that the task is done, write the draft done report to your scratchpad. It lists the deferred Minor findings. Push the branch. Then start the auditor subagent (Sonnet, section 9) with the brief `~/.claude/hooks/workflow-audit/auditor-brief.md`. Give it the worktree path, the path of the draft done report, the path of the verdict file and the PR target (the base branch of the PR). The subagent runs `audit check`, judges L1 to L6 and runs `audit record`. On a pass, open the PR with `gh pr create` (section 8), then report done. On a fail, report each failed item with its evidence and ask the user. Do not fix the failed items yourself. The user can override a failed audit by running `! gh pr create` themselves. A worker of section 7 step 5 does not run this step: the coordinator audits it. A task outside a git repo is not audited.
6. At any cap, stop. Send the user the open findings and the round counts, and ask how to continue.
7. If you're unsure of anything, ask the user.

## 7. General workflow for any task

**Note**: _grilling_ refers to the /mattpocock-skills:grilling skill, already included in the /mattpocock-skills:wayfinder skill.

**Exception:** for small tasks (estimated under ~150 changed lines, tests included), skip steps 1–5: implement directly, then run the section 6 review loop. Judge this once, for the whole task, before step 1. When the user approves a larger task for this path, the session asks with AskUserQuestion, with the approved line count in the question, and writes a `size-approval` event (section 6) with the approved size and the chosen answer as the quote. Once tickets exist, every ticket runs steps 5.1 to 5.5 in full, even a small one.

**Specs and tickets:** publish them to the issue tracker that /mattpocock-skills:setup-matt-pocock-skills configured for the repository. If none is configured, ask the user.

When implementing any task, you must do these steps in the corresponding order:

1. /mattpocock-skills:wayfinder to create a general map for the task.
2. /mattpocock-skills:to-spec after grilling the user, for the general spec.
3. Review the spec with `/plan-review spec general` (its inputs: the spec, the map, the map's resolved decision tickets, and the user's request as a link plus a word-for-word quote). Run the plan-review loop below. The main section 7 session applies every fix to the spec issue body, before any dispatch.
Plan-review loop:
The loop session is the session that runs this loop: the main section 7 session, or the worker in step 5.3. It keeps a findings ledger, as in section 6, with the loop name `plan-review-3`, `plan-review-4.1` or `plan-review-5.3`, and gives its path to `/plan-review`. Each Blocking finding quotes the line it rests on and states what breaks. The loop session writes the quote with `--quote` (required for a plan-review Blocking finding) and a finding that it raises itself with `--raised`. The loop session repairs a finding whose reason lacks its quote with `finding-amend`. The loop session confirms a Blocking finding when its quoted line supports it. Otherwise, the loop session marks it rejected in the ledger and does not fix it.
(a) Run the correctness phase and fix each confirmed Blocking finding, until 1 round has no new confirmed Blocking finding. Record the Minor findings. Cap: 5 rounds.
(b) Apply the recorded Minor findings once.
(c) Run the final phase on the document as changed by (a) and (b). Only confirmed Blocking findings fail a round. The loop session raises a Minor finding to Blocking when it contradicts a decision on the map, or when it shows a requirement that no test can check. For a raised finding, the loop session quotes the map decision or the untestable requirement as its evidence. Fix each confirmed Blocking finding and repeat (c). Mark each new Minor finding in (c) deferred. Do not apply it. Done after 1 round with no confirmed Blocking finding. Cap: 3 rounds.
(d) When the loop ends, list the deferred Minor findings for the user. At any cap, stop and ask the user, with the open findings and the round counts.
This loop differs from section 6 on purpose in two ways. It has no `/simplify`: step (b) only applies the recorded Minor findings. It has no verifier subagent: the quoted line is the evidence, and the loop session confirms it. So the loop session confirms the findings that it raises in (c) itself.
4. /mattpocock-skills:to-tickets after creating the general spec.
4.1. Review the tickets with `/plan-review tickets` (its inputs: the general spec and the ticket issues, each as a link). Run the same plan-review loop as in step 3. The main section 7 session applies every fix in the tracker (edits to the ticket issues and their blocking edges, and any creation, split, merge or closing of ticket issues), before any dispatch.
5. For each one of the created tickets, create its worktree as section 10 says (`orca worktree create --branch <type>/<description> --parent-worktree <your own worktree>`), then dispatch an Orca worker (see section 11) into it with `worker-start --worktree path:<that path>`. The worker executes each of these steps:
5.1. run /mattpocock-skills:wayfinder to get an overview of the map, grilling the user again if needed.
5.2. run /mattpocock-skills:to-spec to generate a specialized spec of that ticket.
5.3. Review the spec with `/plan-review spec ticket` (its inputs: the spec, the ticket and the map). Run the same plan-review loop as in step 3. The worker applies every fix to the spec issue body.
5.4. After the plan-review loop ends, run /mattpocock-skills:implement to implement the spec. Do not go off-topic of the spec; you only have to implement it on this step.
5.5. Review the implementation of the spec with subagents using the axes from /mattpocock-skills:code-review. Use the same logic described on section 6 of this document.
5.6. Push the branch. Put the branch name and the worktree path in the `worker_done` report. Do not open the PR: the coordinator opens it after the audit.

After starting step 5, the original session acts as a **coordinator** of the Orca workers it dispatched.
When a `worker_done` arrives, the coordinator audits the ticket as in section 6 step 5, on the branch and the worktree that the worker reported. This replaces the manual evidence check. After a pass, the coordinator opens the PR with `gh pr create`. On a fail, it reports each failed item with its evidence to the user and asks.
Before the first dispatch, the main section 7 session runs the pre-dispatch audit of its step 3 and 4.1 plan-review loops. It starts the auditor subagent with the pre-dispatch variant of the brief, which runs `audit record --pre-dispatch --worktree <path> --map <issue> --llm <file>`. It gives it the PR target (the base branch of the PR) with the worktree path and the map issue. `--map` takes the map's GitHub issue number or its Linear key (for example `ENG-42`). This replaces the manual step 4.1 evidence check. A hook blocks `orchestration worker-start` until this audit passes; a plain `worker-start --retry-of` for a worker handover is exempt, but a wrapped form such as `bash -c` is not. A context-handoff successor of the main session runs the audit again before its next dispatch. On a fail, it reports each failed item with its evidence to the user and asks.
A worker has no direct channel to the user. To ask the user (grilling included), it must send an Orca `ask` to the coordinator and wait for the `reply`. The coordinator must ask the user and send the answer back to that worker as the `reply`. To list something for the user, it puts the item in its `worker_done` report, and the coordinator passes it on.
A worker never ends its turn while an `ask`, a background test run or a CI watch is open. It waits on them in the foreground (a blocking wait with no short timeout), or it keeps working on parts that they do not touch.
After every `reply` to a worker, the coordinator reads the worker's terminal and confirms that a new turn started. If not, it sends the answer or a wake prompt to the terminal (the Orca terminal send command with submit and wait), and checks again.

## 8. Git contribution

Every task in a git repo ends with a PR, opened with `gh pr create` after a passing audit (section 6 step 5). A hook blocks `gh pr create` until a passing audit record exists for the pushed commit. Only the user may override a failed audit, by running `! gh pr create` themselves. Never do it from the session.
Never add Claude Code attribution to commits, PRs or comments. The `attribution` setting already blanks it; remove any that still appears.
When committing code, you must use the /smart-commits skill.
When merging a PR, follow these rules:
- if **base** is `develop` or `main`, you must squash-merge the PR
- if not, create a merge commit 

A research branch is named `research/<description>`. Its findings are not throwaway: they reach the base branch through the same path as code. The base is `develop` when the repo has one, else `main`. A research subagent cannot push, so the session that started the research (the wayfinder session or a coordinator) commits the findings as `docs/research/<description>.md` on that branch in its own worktree. That session then runs the section 6 review loop, the audit and the PR (section 6 step 5). The owner squash-merges the PR. After the merge, the cleanup rule below applies. This rule covers only `research/*` branches.

Before you give the owner the merge command, check that the CI result of the PR is still valid. Skip this check when the PR has no CI checks. Follow these steps:
1. Fetch the base branch and the PR head: `git fetch origin <base> pull/<n>/head`. The fetch brings the PR head into the local clone, so a tested head that was on the PR branch is there for step 3.
2. If no run exists for the PR, go to step 6.
3. Find the head that the last CI run of the PR tested. First check that the tested head is in the local clone: `git cat-file -e <tested head>^{commit}`. If it is missing (for example after a force push), the CI result is stale: go to step 4. If it is there, check the base tip: if the base tip is an ancestor of that head (`git merge-base --is-ancestor <base tip> <tested head>`), go to step 6. If it is not, go to step 4.
4. If the base tip is not an ancestor of the tested head, or the tested head is stale, merge the base into the PR branch: `gh api -X PUT repos/<owner>/<repo>/pulls/<n>/update-branch`, or `git merge` of the fetched base and a push. `gh pr update-branch` may not exist in the installed `gh`. After the REST call, find the worktree of the PR branch with `git worktree list` (match the branch name). In that worktree, run `git pull --ff-only origin <PR branch>`, so that it holds the new PR head. This needs no upstream on the branch.
5. On a merge conflict, give no merge command: report the conflicting files to the owner and ask how to go on. Do not resolve them on your own.
6. Wait for the CI run on the head with a blocking `gh pr checks --watch`, not a poll loop. If no run appears for the head within about 10 minutes, tell the owner and stop.
7. If the run fails, give no merge command: report the failing check with its link to the owner and ask how to go on. Do not fix it on your own.
8. If you merged the base in step 4, run the section 6 step 5 audit again on the new head.
9. Give the merge command only after the run is green and, when step 8 applied, the audit passed.

Never rebase a PR branch for this: a rebase rewrites audited commits and needs a force-push.

After merging, run `~/.claude/hooks/worktree-cleanup/cleanup <worktree path>`. It is the only cleanup path: it deletes the remote branch (unless the branch is protected), switches the main checkout to the **base** branch, pulls, and removes the worktree and the local branch. For the session's own worktree, finish the report and the memory update first, because the session ends at the last step. On a refusal, fix the cause or ask the user.

## 9. Model selection

When spawning subagents or Orca workers, make sure to use Sonnet models for token reduction. For Orca workers, the /orca-cli skill explains how to set the model.

## 10. Worktrees

Always work inside a git worktree, for every task, including one-line fixes, non-code changes and config repositories (`~/.claude`, dotfiles). Never work directly in the main checkout.
- Create worktrees with /orca-cli, in Orca's configured workspace folder. If Orca isn't running or the repo isn't managed by Orca, stop and ask the user.
- Every Orca ticket worker gets its own child worktree: its parent (lineage) is the coordinator's worktree, and its git base is the repository's default branch, not the coordinator's branch.
- Every branch is named `<type>/<description>`, as the Conventional Branch specification (https://conventionalbranch.org/#specification, version 1.1.0) says. The name tells what the branch does, not who made it.
  - Type, from the label of the issue: bug → `fix`, enhancement → `feat`, documentation or config-only → `chore`. Use `hotfix` or `release` only when the owner asks. With no issue, pick the type by the same meanings. `research/<description>` stays allowed (section 8).
  - Description: lowercase `a-z`, digits and hyphens that say what the branch does. A dot is allowed only between two letters or digits. No leading, trailing or consecutive hyphen or dot. No issue number: the PR and the Orca worktree link the issue. Example: `fix/successor-terminal-close`.
  - Pass the whole name with `--branch <type>/<description>` to `orca worktree create`. The Orca setting Branch Prefix is None. A taken name gets a numeric suffix (`fix/a-b-2`), which is still valid.
  - `orchestration worker-start` cannot name a branch: `--name` turns the slash into a hyphen. So create the worktree first with `orca worktree create --branch <type>/<description> --parent-worktree <the coordinator's own worktree>`, then run `worker-start --worktree path:<that path>`. Never use `--worktree new-child` or `--worktree new-top-level`.
  - The hook `~/.claude/hooks/worktree-branch/check_branch_name.py` denies `orca worktree create` without a valid `--branch`, and `worker-start` with `--worktree new-child` or `new-top-level`. Existing branches keep their names.
- Outside a git repository, skip worktrees and work in place.
- After the branch is merged, clean up with `~/.claude/hooks/worktree-cleanup/cleanup <worktree path>` (see section 8).

## 11. Task delegation

- Use built-in subagents (Agent tool) only for these review runs:
  - /plan-review runs: section 7, steps 3, 4.1 and 5.3.
  - /mattpocock-skills:code-review runs and their verifier subagents: section 6 and section 7, step 5.5.
  - The auditor subagent: section 6 step 5 and section 7.
- Subagents are read-only toward remote state, whatever their prompt says. The hook `~/.claude/hooks/subagent-readonly/block_subagent_writes.py` enforces it for the calls that carry an `agent_id`. It does not cover main sessions or Orca workers, or a write hidden in a script that a subagent runs. Say "read-only" in the prompt of every review subagent anyway.
- Say in the prompt of every subagent that it must not stop or suggest a fresh session for context, and that it must finish the task. Size each brief for one subagent: one review axis, one finding to verify, or one audit.
- Skills that start their own subagents (for example /mattpocock-skills:research or /simplify) may do so. This rule covers subagents you spawn yourself.
- Use Orca for all other delegation:
  - /orchestration: coordinating workers and waiting for results (task DAGs, ask/reply, worker_done, escalations). The section 7 coordinator uses this.
  - A worker never ends its turn while an `ask`, a background test run or a CI watch is open (section 7).
  - /orca-cli: full handoffs, spawning agents in child worktrees, reading or sending to terminals.
- Outside a git repository, ask the user before delegating to Orca workers.
- Context is never a reason to stop:
  - Context size is never a reason to stop, to end a session, or to suggest a fresh session.
  - Only the context-handoff hook ends a session for context. Main sessions (plain and coordinator) and Orca workers keep working until it blocks them.
  - One session may resolve several `/mattpocock-skills:wayfinder` tickets in a row.
  - Charting a map does not end the session. The same session may go on to work the frontier.
  - These plugin rules are cancelled, so a plugin update cannot bring them back:
    - the `/mattpocock-skills:wayfinder` sentence "never resolve more than one ticket per session" (the whole sentence, with its research-ticket exception)
    - the `/mattpocock-skills:wayfinder` charting step "Stop — charting is one session's work; it hand-resolves nothing"
    - the `/mattpocock-skills:ask-matt` advice to `/handoff` and continue in a fresh thread
    - the `/mattpocock-skills:wayfinder` wording "throwaway `research/<name>` branch" (step 5, "Fire the research subagents"), replaced by the research-branch rule of section 8
    - any other skill text that says to stop, end a session or start a fresh session for context reasons
  - `/mattpocock-skills:to-tickets` sizes each slice for one fresh context window. That is ticket sizing, not a reason to stop.
  - Every stop that is not about context keeps working: caps, questions for the owner, a failed audit, confirmation before a destructive action, and any stop defined for a reason other than context.
  - Headless sessions are covered too. The hook skips them; auto-compact is their backstop.

## 12. No polling

Do not poll with filler commands like `echo`, `true`, or `sleep` loops.
If you spawned a background shell, Monitor, subagent, or Orca worker, you will be notified when it finishes. Wait for that notification.
Blocking Orca CLI wait commands are allowed. They are not polling.
A notification with nothing new needs only a text reply, not a tool call.

## 13. Deleting files

Never use `rm -rf` or other recursive deletes. To remove something:
- If it may be needed again, move it to a dated backup folder (`<dir>-backup-YYYY-MM-DD/`) and tell the user the path.
- If it must go, move it to `/tmp`, which the system clears, or give the user the command to delete it manually.
- To remove a worktree folder, use `~/.claude/hooks/worktree-cleanup/cleanup <worktree path>` (section 8). It is the only way a session removes a worktree folder, and the only exception to this rule; the user's `!` overrides are user actions, not session exceptions.

## 14. Docker containers

Docker containers and volumes stay on disk after the session ends. Before you start, or run anything that starts, a container or a `docker compose` stack, and before you remove a worktree, read `~/.claude/docs/agents/docker.md` and follow it. Before you finish, leave behind no container or volume that you created, except a long-lived development stack that you left running or stopped with `docker compose stop`. Remove only the containers and volumes that you created, or that belong to a worktree you remove. Never run any `docker ... prune` command. The cleanup command `~/.claude/hooks/worktree-cleanup/cleanup` refuses while a compose stack has config files in the target worktree; remove such a stack by hand first (ask first when it can hold data), then run the command again.

## 15. CPU load

Other sessions and the user share this PC. Run test runners with at most 2 workers, passed on the command line; do not change committed config for it. If the committed config already sets a lower limit, pass no worker flag and no `VITEST_*` variable. An agent never starts artificial CPU load itself: only the owner starts it, with a `!` command. Before you ask the owner for artificial CPU load, read `~/.claude/docs/agents/cpu-load.md` and follow it.
