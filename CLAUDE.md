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

After implementing code, always run this review loop. It always ends: every loop in it has a round cap.

Finding types:
- **Blocking**: a bug, a logic error, a missing case, a spec mismatch, or weaker security. A spec mismatch is always Blocking, whatever the reviewer called it, and its evidence is the quoted spec line. Any other Blocking finding states a concrete failure: an input or state, and the wrong result. A finding without that evidence is Minor. Ask the reviewers for this evidence in their brief.
- **Minor**: everything else (cosmetic, naming, style, smells, judgement calls).

The main session decides the final type.

Roles. The agent that reports a finding does not fix it, so each fix is checked by an agent that did not write it:
- **Reviewers** (the /mattpocock-skills:code-review subagents) report findings. They do not fix.
- **Verifier**: one Sonnet subagent per Blocking finding. It confirms the failure from the code (a failing test, a traced path, or a quoted line), or it rejects the finding.
- **Fixer**: the main session. For each confirmed Blocking finding: (1) write a test that reproduces it, where the change can be tested, (2) list the callers and the tests that the fix can affect, (3) apply the smallest fix, (4) run the affected tests.

Ledger: the main session keeps one findings ledger per task in the scratchpad. Each entry has an id, `file:line`, the type, the status (open, fixed, rejected or deferred) and a one-line reason. Give the ledger to every reviewer. A finding that matches a ledger entry is not new. Reviewers do not report rejected or deferred entries again, unless they add new evidence.

1. **Blocking loop.** Run /mattpocock-skills:code-review, verify each Blocking finding, then fix each confirmed one. Record the Minor findings in the ledger. Every round reviews the full diff, and reviewers report only findings that are new to the ledger. Done after one round with no new confirmed Blocking finding. Cap: 5 rounds.
2. **Minor pass (once).** Commit first, so step 3 has a fixed point. Sort the open Minor findings into two groups:
   - Apply: a change in one file, with no behavior change and no public interface change.
   - Defer: everything else. Mark it deferred in the ledger.
   Apply the first group in one pass, then run the tests. If a test fails, revert the Minor change that broke it and mark that finding deferred. Then run /simplify once and run the tests again. If a test fails, revert all the /simplify changes.
3. **Final check.** Run one /mattpocock-skills:code-review round on the diff since the commit made at the start of step 2. Only Blocking findings count; record any new Minor finding as deferred. Verify and fix each confirmed Blocking finding as in step 1, then repeat this step. Each repeat reviews the diff from that same commit, which now includes the fixes. Done after one round with no confirmed Blocking finding. Cap: 3 rounds.
4. **Report.** List the deferred Minor findings for the user. Leave them unfixed in this task, because fixing them would reopen the review.
5. At any cap, stop. Send the user the open findings and the round counts, and ask how to continue. If you're unsure of anything, ask the user.

## 7. General workflow for any task

**Note**: _grilling_ refers to the /mattpocock-skills:grilling skill, already included in the /mattpocock-skills:wayfinder skill.

**Exception:** for small tasks (estimated under ~50 changed lines), skip steps 1–5: implement directly, then run the section 6 review loop. Judge this once, for the whole task, before step 1. Once tickets exist, every ticket runs steps 5.1 to 5.5 in full, even a small one.

**Specs and tickets:** publish them to the issue tracker that /mattpocock-skills:setup-matt-pocock-skills configured for the repository. If none is configured, ask the user.

When implementing any task, you must do these steps in the corresponding order:

1. /mattpocock-skills:wayfinder to create a general map for the task.
2. /mattpocock-skills:to-spec after grilling the user, for the general spec.
3. Review the spec with `/plan-review spec general` (its inputs: the spec, the map, the map's resolved decision tickets, and the user's request as a link plus a word-for-word quote). Run the plan-review loop below. The main section 7 session applies every fix to the spec issue body, before any dispatch.
Plan-review loop:
Each Blocking finding quotes the line it rests on and states what breaks. The session that runs the loop keeps a findings ledger, as in section 6, and gives it to every reviewer. That session is the main section 7 session, or the worker in step 5.3.
(a) Run the correctness phase and fix each Blocking finding, until 1 round has no new Blocking finding. Record the Minor findings. Cap: 5 rounds.
(b) Apply the recorded Minor findings once.
(c) Run the final phase on the document as changed by (a) and (b). Only Blocking findings fail a round. That session raises a Minor finding to Blocking when it contradicts a decision on the map, or when it shows a requirement that no test can check. Fix each Blocking finding and repeat (c). Done after 1 round with no Blocking finding. Cap: 3 rounds. A new Minor finding in (c) is recorded and listed for the user, not applied.
(d) At any cap, stop and ask the user, with the open findings and the round counts.
This loop differs from section 6 on purpose in two ways. It has no `/simplify`: step (b) only applies the recorded Minor findings. It has no verifier subagent: the Blocking finding's quoted line is the evidence, and that session checks it. When the quoted line does not support the finding, that session records it as rejected in the ledger and does not fix it.
4. /mattpocock-skills:to-tickets after creating the general spec.
4.1. Review the tickets with `/plan-review tickets` (its inputs: the general spec and the ticket issues, each as a link). Run the same plan-review loop as in step 3. The main section 7 session applies every fix in the tracker (edits to the ticket issues and their blocking edges, and any creation, split, merge or closing of ticket issues), before any dispatch.
5. For each one of the created tickets, dispatch an Orca worker (see section 11) that executes each of these steps:
5.1. run /mattpocock-skills:wayfinder to get an overview of the map, grilling the user again if needed.
5.2. run /mattpocock-skills:to-spec to generate a specialized spec of that ticket.
5.3. Review the spec with `/plan-review spec ticket` (its inputs: the spec, the ticket and the map). Run the same plan-review loop as in step 3. The worker applies every fix to the spec issue body.
5.4. After the plan-review loop ends, run /mattpocock-skills:implement to implement the spec. Do not go off-topic of the spec; you only have to implement it on this step.
5.5. Review the implementation of the spec with subagents using the axes from /mattpocock-skills:code-review. Use the same logic described on section 6 of this document.

After starting step 5, the original session acts as a **coordinator** of the Orca workers it dispatched.
Before reporting a ticket as done, the coordinator checks evidence for each step: the spec link in the issue tracker, the spec-review result, the round count of each section 6 loop (steps 1 and 3) and of each phase of the plan-review loop, `git log` showing /smart-commits-style messages without attribution, and the model of each review subagent. A worker's claim without evidence counts as not done. Before any dispatch, the main section 7 session checks the following evidence for the step 4.1 review: its result, the round count of each phase of its plan-review loop, and the model of each plan-review subagent.
These steps are mandatory.
A worker has no direct channel to the user. To ask the user (grilling included), it must send an Orca `ask` to the coordinator and wait for the `reply`. The coordinator must ask the user and send the answer back to that worker as the `reply`. To list something for the user, it puts the item in its `worker_done` report, and the coordinator passes it on.

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

Always work inside a git worktree, for every task, including one-line fixes, non-code changes and config repositories (`~/.claude`, dotfiles). Never work directly in the main checkout.
- Create worktrees with /orca-cli, in Orca's configured workspace folder. If Orca isn't running or the repo isn't managed by Orca, stop and ask the user.
- Every Orca ticket worker gets its own child worktree: its parent (lineage) is the coordinator's worktree, and its git base is the repository's default branch, not the coordinator's branch.
- Outside a git repository, skip worktrees and work in place.
- After the branch is merged, delete the worktree before deleting the local branch (see section 8).

## 11. Task delegation

- Use built-in subagents (Agent tool) only for these review runs:
  - /plan-review runs: section 7, steps 3, 4.1 and 5.3.
  - /mattpocock-skills:code-review runs and their verifier subagents: section 6 and section 7, step 5.5.
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

## 14. Docker containers

Docker containers and volumes are durable. They stay on disk after the session ends. Section 13 covers files; for Docker objects, follow this section.
- Start one-off and test containers with `docker run --rm`.
- Start containers that run browsers or spawn many processes with `--init`.
- When a long-running container is no longer needed, stop and remove it with `docker rm -fv <name>`.
- Stop a test or throwaway `docker compose` stack that you started with `docker compose down -v`. For a long-lived development stack (for example, a local dev database), use `docker compose stop`, or leave it running. Do not use `down` on it: `-v` deletes its data, and without `-v` its volumes lose their containers, so `docker compose ls -a` can no longer find them.
- Before you remove any worktree, run `docker compose ls -a` and remove each stack whose config files are in that worktree with `docker compose -p <NAME> down -v`, where `<NAME>` is the stack name from that list. Compose names the stack after the folder by default, so no later run uses its volumes. If the stack can hold data that the user wants, ask first.
- Before you finish, check with `docker ps -a` and `docker volume ls -f dangling=true` that you left no container or volume behind. Exception: a long-lived development stack that you left running or stopped with `docker compose stop`.
- Remove only the containers and volumes that you created, or that belong to a worktree you remove. Never run any `docker ... prune` command.

## 15. CPU load

Other sessions and the user share this PC. Parallel test runners and artificial CPU load (busy loops, `stress-ng`, "burners") slow it down, and burners keep running after the session ends.
- Run test runners with at most 2 workers, for example `vitest --maxWorkers=2`, `stryker run --concurrency 2`, `playwright test --workers=2`, `jest --maxWorkers=2`. Pass the limit on the command line; do not change committed config for it. If the committed config already sets a lower limit (such as `workers: 1`, `maxWorkers: 1`, or `fileParallelism: false`), pass no worker flag and no `VITEST_*` variable: they override the config and can make a serial suite run in parallel.
- Use at most half of the cores for burners: start at most `nproc / 2` burners, one per core, pinned with `taskset -c` to cores `0` to `nproc / 2 - 1`. Pin the code under test to the same cores: a host process with `taskset -c`, a container with `--cpuset-cpus`. The other cores stay free.
- Wrap each burner in `timeout` of at most 30 minutes. Start new burners if you need more time. A short timeout stops orphaned burners if your session dies.
- Write the PIDs that you start to a file in your scratchpad: each Bash call starts a new shell, so `$!` is lost. Before you finish, kill only the PIDs whose command (`ps -o args= -p <PID>`) is still your burner. Then check again the same way that none of them is still your burner. Do not use `pgrep -f` for this check: it also matches the shell that runs it.
- If the problem does not reproduce at this load, ask the user. Never raise the load by yourself.
