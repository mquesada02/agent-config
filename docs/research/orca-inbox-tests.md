# Test and review friction on long and docs-only changes

Research for ticket 756 of map 752 (request 750). Date of reading: 2026-11-17. Marks: **FACT** = read in a file or a command output. **INFERENCE** = our reading. The owner decides; this file makes no decision.

## Question

The declared test command runs in the foreground and takes about 50 minutes (ticket text). A docs-only change still runs the full command, the review loop and the audit. What do the audit checks (S2 and others) require? What do they allow? What options exist: background runs with a blocking wait, test selection by changed path, a docs-only path with its own checks? Include issue 729 (S2 and the 600 s Bash limit) and the cost of each option.

## Short answer

1. S2 requires one thing: the declared command, as exact text, ran after the last Edit, Write or NotebookEdit inside the worktree, and finished with success. It never looks at which file changed. FACT (`hooks/workflow-audit/audit`, `check_s2`).
2. A docs-only change is not special for S2. Only a declared value of `none` skips S2, and it skips it for the whole repo.
3. Issue 729 is still open. S2 already accepts a run with `run_in_background: true` plus a task notice with exit code 0. It does not handle a foreground call that the harness moves to the background after its timeout.
4. INFERENCE from the code and from a live example: such an auto-backgrounded call can pass S2 by accident (empty stdout) and does not prove that the suite passed. Issue 729 describes a failure; the code read suggests a false pass. A test must settle this.
5. In 20019 local transcripts, 3 foreground runs of the declared command lasted 523, 601 and 603 s. The "about 50 minutes" figure is not confirmed by any transcript (a foreground call stops at 600 s).
6. Options: A (background run with a blocking wait, no audit change), B (S2 reads auto-backgrounded calls), C (a wrapper script that selects tests by path, as the one declared command), D (a docs-only rule in S2), E (declare `none`, and rely on a CI run). Combine A with B first; C and D change what the audit proves.
7. In this repo, "docs-only" is hard to define: 44 test files read Markdown files (CLAUDE.md, skills). A docs edit can break a test.

## Findings

### F1. What S2 requires

- FACT: the declared command is the single fenced block of the one `### Test command` section in `.claude/CLAUDE.md`, `CLAUDE.md` or `AGENTS.md`; zero or two sections fail S2 (`_declared_command`, `_sections`, lines 842 to 855). The value `none` passes S2 with "no tests declared" (line 886).
- FACT: a Bash call counts as a run when `declared in command` and the normalised command equals the declared text (line 920). Normalising removes a leading `cd <worktree> &&` and, for a foreground call, the `|| echo command-failed` suffix of the redact hook (lines 890 to 904). A pipe or a redirect makes the text differ, so the run does not count. The auditor brief and the memory note "never pipe the declared command" say the same (`hooks/workflow-audit/auditor-brief.md` line 61 covers the `!` case).
- FACT: every Edit, Write or NotebookEdit whose path is inside the worktree is an edit, whatever the file (line 918, `EDIT_TOOLS` line 119). A run must come after all edits: `all(_is_after(run, edit) ...)` (line 924). One more edit after the last run, even a comment in a Markdown file, makes S2 fail with "ran only before the last edit".
- FACT: a foreground run passes when its tool result is not an error, has one stdout, and the last stdout line is not `command-failed` (`foreground_outcome`, lines 906 to 912). The exit code is not read; S2 trusts the redact hook suffix.
- FACT: a run with `run_in_background: true` passes only when a task notice with the same `tool-use-id` says `completed` and `(exit code 0)` (`_notification_exit`, lines 864 to 877). Tests: `test_transcripts.py` lines 684 to 721 (user rows, attachment rows, a subagent run reported in the main transcript, failed and missing notices).
- FACT: edits outside the worktree, such as the draft done report in the scratchpad, are not edits for S2.
- FACT: other checks that touch tests. S9 (lines 1966 to 2070) denies a runner with more than 2 workers (pytest `-n`, vitest `--maxWorkers`, jest, playwright, cargo, go); the declared unittest command has no worker flag, so it passes. S8 reads commit messages and has no test rule. S3, S4, S5, S6, XC, S10 read the ledger; none reads test results. L1 to L6 are judged by the auditor from the digest; L4 compares the done report claim "tests run" with S2.
- FACT: record statistics. Of 852 local audit records (folder of the audit runtime, read as aggregates only): S2 passed in 608; "no or two Test command sections" in 129 (records of other repos with no declaration); "did not run" in 12; "ran after the last edit but failed or did not finish" in 7; "ran only before the last edit" in 1; 2 "evidence unavailable". INFERENCE: in this record set S2 fails rarely on the order rule; most failures are missing declarations.

### F2. What CLAUDE.md requires of a test run

- FACT (CLAUDE.md section 6): the fixer writes a reproducing test and "Run the affected tests" per fix; the quality phase says "Apply the first group in one pass, then run the tests" and "run /simplify once and run the tests again". Section 6 never says "run the full declared command"; S2 does.
- FACT (section 15): at most 2 workers on the command line; a worker never ends its turn while "a background test run" is open (section 7). Section 12: no polling; "Blocking Orca CLI wait commands are allowed".
- FACT (section 7 Exception): a task under about 150 changed lines skips steps 1 to 5 but still runs the section 6 loop, S2 and the audit. No rule exists for docs-only changes.
- FACT: this repo has no CI (`.github/workflows` does not exist). The local declared command is the only test gate.

### F3. Size and duration of the declared command

- FACT (static count of `def test_` lines, no test run): 4938 test methods in 12 folders: workflow-audit 1241, sql tests 1653, cicd-pipelines tests 735, redact-secrets 606, context-handoff 310, worktree-cleanup 202, setup-diff-prompt 73, plan-review 30, bash-reader 29, subagent-readonly 29, worktree-branch 25, forked-skills 5.
- FACT (scan of 20019 local transcript files, matching Bash calls with the declared text): 10 calls. 3 were foreground: 523 s, 601 s and 603 s from call to result. 7 were `run_in_background`: the call returned in 0 to 2 s (the run time is in the notice, not measured here).
- INFERENCE: a foreground call that lasts 601 s was stopped by the 600 s limit, so the real run time is not known from these three calls. The "about 50 minutes" in the ticket is not confirmed or refuted here. No ledger or record stores a test duration.
- FACT: the declared command lists all 12 folders in one process, so a change to one skill file still runs the other 11 (`.claude/CLAUDE.md`, Test command).

### F4. Issue 729 and the 600 s limit (still open)

- FACT: issue 729 is open with labels `bug` and `needs-triage`, and has no comments. It says: after 600 s the harness moves the command to the background, the transcript holds partial output and the note "moved to the background", and S2 fails.
- FACT (this session, a live example with a 120 s default timeout): a foreground call that outlived its timeout returned a non-error result with `stdout: ""`, `backgroundTaskId` and `timedOutAfterMs: 120000`, and a task notice later arrived with the `tool-use-id` of the call, `status` `completed` and the summary ending `(exit code 0)`. The call row has no `run_in_background` field.
- FACT: `check_s2` sets `background` only from `run_in_background is True` (line 558). An auto-backgrounded call is therefore read as a foreground call: `last_lines` holds `""` (not `None`), so `foreground_outcome` returns True. INFERENCE: S2 then passes, even if the suite later fails or never finishes. This is the opposite of the failure that 729 describes. We did not run a test to confirm it; the check is cheap (one S2 test with a result row that has an empty stdout and a `backgroundTaskId`).
- INFERENCE: the notice carries the same `tool-use-id`, so the existing `_notification_exit` could read an auto-backgrounded call without a new format.
- FACT: the Bash tool maximum for a foreground timeout is 600000 ms (tool text). A declared command that needs more than 600 s cannot finish in the foreground.

### F5. What a docs-only change costs today

- INFERENCE: for a docs-only change the steps are: full declared command (S2), the section 6 loop with reviewers and verifiers (S3, S4, S5, XC, S10), a commit, the audit with an auditor subagent, then a PR. Only S2 depends on the test run; the others depend on the loop and are independent of file type.
- FACT: in this repo Markdown is not inert. 44 test files reference `.md` files; `test_claude_md.py` tests the rules and the test declaration of CLAUDE.md. A docs-only edit of CLAUDE.md or a SKILL.md can change a test result.
- FACT (prior research, `docs/research/agent-workflow-comparison.md`, section 3): public sources keep a lightest path chosen by facts or by the human (BMAD, Spec Kit, Kiro, Superpowers, EGM "Track 1" size rule). No source describes an audit record or a rule that exempts docs from tests. INFERENCE: option D has no public model to copy.

## Options for the owner

Costs are INFERENCE unless a source is named.

### A. Run the declared command in the background and wait for the notice (no audit change)

- Change: the session starts the exact declared text with `run_in_background: true`, then waits for the completion notice (one blocking wait, no polling), then reads the output file.
- What it fixes: runs longer than 600 s; S2 already accepts it (F1). Section 7 already says a worker waits on a background test run in the foreground.
- Cost: no audit change. The session must remember the form; a call without the flag falls into the 729 gap. The run still takes the full time (about 50 minutes per ticket). The wait uses a Monitor or a notice; a worker must not end its turn while it is open. A peer message that arrives during the wait can interrupt the turn.

### B. Make S2 read an auto-backgrounded call (fixes 729 itself)

- Change: S2 treats a call whose result has `backgroundTaskId` as a background run, and reads the notice with the same `tool-use-id`. One new test row shape in `test_transcripts.py`.
- What it fixes: both the 729 failure case and the possible false pass of F4. It makes S2 correct for the foreground form that sessions use by habit.
- Cost: an audit change that depends on a Claude Code transcript field (`backgroundTaskId`). The audit supports tested versions only (`TESTED_VERSIONS`, one version), so a field rename needs a new fixture. Small code change (INFERENCE: under 40 lines with tests).

### C. A wrapper script as the declared command, with test selection by changed path

- Change: the one declared command is a script (for example `bash scripts/run-tests.sh`) that reads `git diff --name-only <base>` and runs only the folders that the changed paths map to.
- What it gives: shorter runs for small changes; S2 needs no change, because it compares text and the script is one text.
- Cost: S2 then proves only that the script ran, not what it covered. The map from path to folder must carry dependencies: audit imports the context-handoff folder (`CONTEXT_HANDOFF_DIR` near the top of the file), and 44 test files read Markdown (F5); a wrong map hides a failure. A change to the script itself or to the map must run everything. The rule "never pipe the declared command" still holds, so the script prints its own summary. The script is new code in a config repo and needs its own tests. The owner must decide who owns the dependency map.

### D. A docs-only path in S2 (own rule)

- Change: S2 passes without a run when every edit path of the branch is in a listed set of non-code paths, or the repo declares a second command for docs.
- What it gives: skips the full run for typo and note changes.
- Cost: the audit must define "docs-only" by paths, and the set cannot include `CLAUDE.md`, `SKILL.md` or `docs/` files that tests read (F5). In this repo the set would be small (for example `docs/research/*.md`). S2 loses its rule "one command, one proof" and gets a second code path to test. The edit-path rule must also cover the commit, not only the Edit calls: a Bash write is not seen by S2 today. Other checks (S3 to S10, L1 to L6) still apply.

### E. Declare `none` and use a CI run as the test gate

- Change: set the declaration to `none` and add a CI workflow that runs the command on each PR.
- What it gives: no foreground wait in the session; S2 passes by declaration.
- Cost: S2 stops proving anything for this repo; the audit would need a new item that reads the CI result (`gh pr checks`). The repo has no CI today (F2), the section 8 rule for merge waits on CI only when checks exist, and the section 15 limit of 2 workers would apply to a runner owned by someone else. The change is the largest of the five.

### Combinations (INFERENCE)

- A with B is the smallest set that makes long runs sound: the session uses the safe form, and the audit stops accepting the unsafe one by accident.
- C can follow A and B when the run time still hurts; D is the most visible saving for docs, with the narrowest safe set in this repo.

## Gaps and open questions

1. The real duration of the declared command is not measured. The three foreground calls were cut at about 600 s. A timed background run would give it (needs a test run, outside this ticket).
2. The false pass of F4 is read from code and from one live example, not from an S2 test. A one-case test would settle it.
3. Whether the harness limit of 600 s is a fixed value or a setting was not read from a primary source here (the tool text only).
4. No test timing per folder exists, so the saving of option C is not known. The static counts (F3) are a weak proxy.
5. The audit record folder holds records of other repos; only aggregates were used.
6. How many tasks per month are docs-only was not counted (records do not store file types).
7. Review and audit time for docs-only changes was not measured; no ledger or record stores the time of a loop.
8. The 2026-11-16 research (`agent-workflow-comparison.md`) has no data on test selection or docs-only exemptions.

## Sources read and sources that failed

Read:
- `hooks/workflow-audit/audit` lines 1 to 160, 386 to 940, 1948 to 2070 (S2, S1, S7, S9, transcript reader); docstrings of S3 to S6, S8, S10, XC.
- `hooks/workflow-audit/auditor-brief.md` (whole file).
- `hooks/workflow-audit/test_transcripts.py` lines 660 to 730 (S2 tests).
- `.claude/CLAUDE.md` (declared test command), `CLAUDE.md` sections 6 to 8, 12 and 15 (as loaded in the session).
- `docs/research/agent-workflow-comparison.md` (whole file).
- Issues 752, 756 and 729 (REST `gh api`), comments of 729 (none).
- The local session transcripts (aggregate scan, 20019 files) and the audit runtime records (852 with an S2 item, aggregates).
- A local transcript row of an auto-backgrounded call and its notice (described, not quoted).
- Static counts of test files and `def test_` lines.

Failed or not done:
- Not run: the declared test command, any test runner, any container (by brief).
- `gh issue view` was not used (GraphQL deprecation); REST was used.
- No web sources were read: the question concerns local audit code. No subagent was started.
- A first Bash call of the scan hit the harness timeout and moved to the background (the example in F4); it completed.
