# Workflow audit checks: false fails, background test runs and owner overrides

Question (issue 799): which checks of the workflow audit (`hooks/workflow-audit`) fail when the work was correct, how often does the owner override a failed audit, and what does each check protect? Owner priority (the owner's comment on issue 799, 2026-11-17): "let the tests run in the background without failing the audit".

Date of reading: 2026-11-17. Marks: **FACT** = read from code, a test, a stored record, or counted by a method named in the text. **INFERENCE** = our reading. **UNTESTED** = not run. No audit code was changed. Transcript text is not quoted: only counts are given.

Terms. S1 to S10 are checks that the `audit` script computes. XC is the cross-check of reviewer and verifier agents. L1 to L6 are items that an auditor subagent judges from a digest. The pre-dispatch variant is the shorter audit that runs before the first worker dispatch. S2 is the check "the declared test command ran after the last edit and passed".

## Short answer

1. FACT: S2 counts a passing background run only when the Bash call, after an optional `cd <worktree> && ` prefix, equals the declared command text exactly. Any other step in the same call (`git commit ... && cd W && <cmd>`, `cd W && git log && <cmd>`, `cd W; <cmd>`, `<cmd> 2>&1`, `<cmd> > file`, `| tail`) makes the run "not the declared command" (`hooks/workflow-audit/audit:890-920`). Issue 796 is real.
2. FACT: a foreground call that the harness moved to the background is not read as a background run. S2 reads only the partial stdout of the first result and accepts it, whatever the exit code later was (`audit:906-931`, no code path for `backgroundTaskId` or `timedOutAfterMs`). Issue 729 describes a fail; the code and the data show a pass, and in 5 of 56 eligible cases a false pass.
3. FACT: this happens a lot. In 439 declared-command calls found in transcripts of this repo, 79 were foreground calls that the harness moved to the background (66 at the 600 s limit, 11 at 120 s, 2 because a message arrived).
4. FACT: of the 439 calls, 31 ended with exit code 0 but are refused by S2 on form (15 background, 12 moved foreground, 4 plain foreground; extra steps, redirects or `;`). 15 more exit-0 runs are refused as stale or edited copies of the declared block; these are probably partial runs (counts in the 1.5 table row on stale copies and in table 1.9).
5. FACT: in stored records of this repo, S2 failed in 4 of 199 records (2 percent). 2 of the 4 look like form problems, 1 was an unfinished run, 1 is undetermined. Most S2 fails in the record store (133 of 158) are repos with no declared test command, which is a setup gap, not a form problem.
6. FACT: the cost shows more in reruns than in stored fails. 948 audit record outputs exist in transcripts, against 775 stored records. INFERENCE: many of the extra outputs were replaced by a later record of the same commit.
7. FACT: overrides. 26 of 184 PRs of this repo since the first record had a failed last record at the PR head. 12 of them match an owner `!` `gh pr create` command in the transcripts (lower bound). The checks in those 12: S9 8, S1 6, L4 3, S5 2, S2 2, L2 1, S7 1.
8. FACT: S1 had 13 fails, all memory-note edits, all before the exemption (PR 255). All 13 were false. S9 had 19 fails in this repo; 5 evidence rows are `rm -r` used as a command word, the rest are parser limits or text that only looked like a command.
9. INFERENCE: the checks with the most false fails by count are S2 (setup gap and form), S9 (61 evidence rows say "cannot split the command", and 50 of those commands ran fine), S8 (26, all in other repos, 20 of them dated before the merge-commit exemption), and L5 (rule drift between the brief and CLAUDE.md).
10. Limits: the record store keeps only the last record per commit; the override test is an inference; other repos' transcripts were not classified (section "Method").

## 1. S2 and background runs

### 1.1 What S2 does today (FACT)

- The declared command is the one fenced block of the one `### Test command` section in `.claude/CLAUDE.md`, `CLAUDE.md` or `AGENTS.md` at HEAD (`audit:842-855`). Zero or two sections fail S2. The value `none` passes.
- A call is a candidate when its text contains the declared command (`audit:920`, `declared in call["command"]`). It counts as a run when `normalised(call) == declared` (`audit:890-905`).
- `normalised`: strip a leading `cd <path> && ` when the path resolves to the worktree (`CD_PREFIX`, `audit:122`, matched at the start only, `audit:892`). With no such prefix, the call row's cwd must be inside the worktree. A foreground call may end with the redact suffix ` || echo command-failed`, stacked any number of times (`audit:902-903`); a background call may not.
- All runs must come after the last Edit, Write or NotebookEdit inside the worktree (`audit:921-925`). A Bash-made file write is not an edit for S2.
- One passing run is enough (`audit:932-933`).
- Background run (`run_in_background: true`): passes only when a `<task-notification>` with the same `tool-use-id` says `completed` and its summary ends with `(exit code 0)`; every notification of that id must agree (`audit:864-877`, `audit:927-929`). A subagent's background run may be reported in the main transcript.
- Foreground run: passes when the result is not an error, the row has one stdout, and the last stdout line is not `command-failed` (`audit:906-913`). The exit code is never read.
- The fail text has three forms: "did not run", "ran only before the last edit", "ran after the last edit but failed or did not finish" (`audit:935-938`). "Did not run" does not say why a call was refused (issue 796).

### 1.2 Case A: background call with the declared command plus another step (issue 796)

- What S2 does: `git commit ... && cd W && <cmd>` has no `cd` prefix at the start, so the text stays whole and is not equal to the declared text. `cd W && git log -1 && <cmd>` loses only the `cd` prefix, and `git log -1 && <cmd>` is not equal either. Fail text: "did not run" (`audit:892-905`, `audit:920`).
- Test that pins it: `test_a_filtered_or_piped_run_is_not_the_declared_command` (`test_transcripts.py:657`) pins `| tail`, extra arguments, `2>&1`, `cd /other && ...` and `echo ...`. FACT: no test names a `git ... &&` step before the command or after a correct `cd`. The behavior follows the same equality line, but it is not pinned by name.
- How often (FACT, scan of 5,104 transcript files of this repo's worktrees): 24 calls had another step before the declared command (13 background, 9 moved foreground, 2 foreground); 14 of the 24 ended with exit code 0. In stored records: PR 797's record (S2 and L4 failed) is this case: two background runs with `cd W && <other step> && <cmd>` and exit code 0 (matched by time and by the L4 evidence text).
- Options, unranked:
  - A1. Accept the declared command as one segment of an `&&`-only chain. FACT about shells: if the whole chain exits 0, every segment ran and passed. It needs the audit's own command splitter (`split_command`, `audit:2668`) and a check that no `cd` moves the working directory away from the worktree. Stops catching: nothing about test success. It would no longer prove that the call was "just the tests"; a chain with a command that edits files after the tests passed (`<cmd> && sed -i ...`) would count unless segments after the declared command are refused.
  - A2. As A1 but allow only a short allowlist before the declared command (`cd`, `git log`, `git status`, `git commit`, `git add`). Stops catching: the same as A1 for other steps; adds a list to maintain.
  - A3. Keep the strict match and name the closest refused call in the fail text (second direction of issue 796). Stops catching: nothing. Does not remove the rerun; it only makes the cause visible.

### 1.3 Case B: foreground call moved to the background by the harness

- Forms in the transcripts (FACT): the tool result of the first row either carries partial stdout (the output so far) and `toolUseResult.backgroundTaskId` with `timedOutAfterMs` (600000 or 120000), or the text "Command was moved to the background (ID: ...)" with `backgroundedToDeliverMessage: true` (a message arrived). The `tool_use` input has no `run_in_background`. The exit code arrives later in a `<task-notification>` with the same `tool-use-id`; the task id is also in the notice.
- What S2 does (FACT, code): `background` is set only from `run_in_background is True` (`audit:558`). The call is read as foreground. `last_lines` holds the partial stdout (or an empty string), not `None`, so `foreground_outcome` returns True unless the partial output ends with `command-failed` or the result is an error (`audit:906-913`). S2 passes at once and never reads the notification. A search of `audit` and all tests finds no use of `backgroundTaskId`, `timedOutAfterMs` or "moved to the background": no test pins this behavior.
- Data (FACT): 79 moved calls (66 at 600 s, 11 at 120 s, 2 by message). 56 have a form S2 accepts. For those 56 the notice says: exit 0 in 51; failed (exit 1) in 1; stopped by a kill in 1; no notice in 3. So S2 passed 5 of 56 without proof, 2 of them against a failing or killed run.
- Record check (FACT, branch join of records with transcripts): 10 branches of this repo have only moved runs as their passing runs, and S2 passed on all 10. This matches the code and does not match the failure that issue 729 describes. INFERENCE: the failure in 729 may come from another cause in that session (a pipe, a redirect or a chain), as case A shows; we did not find that session.
- Options, unranked:
  - B1. Do nothing. Stops catching: nothing new; keeps the 5 false passes of the sample (3 of them unknown).
  - B2. Read `backgroundTaskId` in the tool result row. When it is set, treat the call as a background run and demand a notice with exit code 0 (the same `_notification_exit`). Stops catching: nothing. Closes the false pass. Adds a fail when the notice is missing (3 of 56 here); the session must wait for the notice, which section 7 already asks of workers.
  - B3. As B2, and also accept the task output file only when it holds the declared command's exit code. Not supported today: the output file holds stdout, not the exit code (UNTESTED for what the harness writes).

### 1.4 Case C: run longer than the 600 s Bash limit (issue 729)

- FACT: in this sample 66 declared-command calls hit the 600 s foreground limit. Runs in the background have no such limit, and S2 accepts them when the call is exact (256 of 312 exact background calls have an exit 0 notice; 37 have no notice; 19 have a failed or killed notice).
- FACT: for a foreground call that crosses 600 s, S2 behaves as in case B (pass on partial output).
- The 37 background calls with no notice (FACT, counted over all transcripts): the session ended, was cut, or read the output file instead of waiting. S2 fails these unless another run passes. INFERENCE: a notice only arrives while the session still runs; a call made late may never report.
- Options, unranked:
  - C1. Document one supported form: `run_in_background: true`, exact command text, then a blocking wait for the notice. It works today. Stops catching: nothing. It relies on the habit; 79 of 105 foreground calls show that the habit is not there yet.
  - C2. Combine with B2 so the habit is not needed. Stops catching: nothing.
  - C3. A wrapper script as the one declared command that writes `<tree hash> <exit code>` to a file in the audit runtime folder, and S2 reads the file for the pushed tree. Stops catching: nothing; adds proof that the tested tree is the pushed tree (S2 today only compares with the last Edit call; Bash writes are invisible). Costs: new code and tests; the file is written by the session, so it is a claim, not a proof, unless the runtime folder is writable only by the wrapper (UNTESTED).

### 1.5 Case D: pipes, redirects, `;`, redact suffix, stale copy, other

| Form | S2 result | Pinned by test | Calls found (of 439) | Exit-0 calls refused |
|---|---|---|---|---|
| `... 2>&1` or `> file` after the command | refused (text differs) | `test_transcripts.py:657` pins `2>&1`; a redirect to a file is not pinned (UNTESTED) | 46 calls have `2>&1` or a redirect (41 `2>&1`, 5 redirect); 18 of them are exact except for that tail | 13 |
| `cd W; <cmd>` (semicolon) | refused; `CD_PREFIX` needs `&&` (`audit:122`) | none (UNTESTED) | 10 | 4 |
| `| tail`, other pipe | refused | `test_transcripts.py:657` | 0 found | 0 |
| ` || echo command-failed` on a foreground call | accepted; a failing stdout line fails it | `test_transcripts.py:582-603` | 5 | n/a |
| same suffix on a background call | refused: the suffix hides the exit code | `test_transcripts.py:634` | 0 | 0 |
| a copy of the declared block that is not the one at HEAD | refused | none by name | 22 (19 foreground, 3 moved) | 15 |
| other prefix (a variable, `source`, an `export`) | refused | none by name | 16 | not counted |
| owner `!` run | invisible: the transcript has no tool result | stated in `auditor-brief.md:61` | 0 owner test runs found in transcripts | n/a |
| Edit or Write in the worktree after the run, even a Markdown file | "ran only before the last edit" | `test_transcripts.py:533-558` | 1 record | n/a |
| declaration changed by a rebase onto the base branch | the HEAD text differs from the text that was run | none | declaration changed 11 times between 2026-10-23 and 2026-11-16 (git log of the file) | unknown |

Notes:
- FACT: the 22 "stale or edited" copies are not equal to any committed declaration. INFERENCE: most are partial runs (a subset of folders) or runs of an older declaration; S2 is right to refuse a partial run. We did not read them one by one.
- FACT: the declaration text is read at HEAD, so a rebase that adds a folder to the declaration makes every earlier run stale. One L4 fail in this repo shows a done report that claimed the full command while the runs lacked a folder added on the base branch. That is a real catch (see Section 2, L4).
- Options, unranked:
  - D1. Accept `2>&1` and `> file` after the command when the call is a background run with an exit 0 notice (the exit code is the command's own). Stops catching: nothing about success. A redirect to a file hides output from the transcript; the session loses the printed summary (no change for S2).
  - D2. Treat `;` like `&&` when the declared command is last (the exit code is the command's). Stops catching: nothing about the declared command's result.
  - D3. Refuse pipes always (keep today). A pipe's exit code is the last command's unless `pipefail` is set, so `| tail` can hide a failure. Stops catching: nothing new; it keeps refusing passing runs that use a pipe.
  - D4. Name the refused form in the fail text (a list of: extra step before, extra step after, redirect, pipe, stale copy, outside worktree). Stops catching: nothing; costs a few lines and tests.

### 1.6 Case E: other ways a passing run fails S2 (FACT)

- A background call with no notice before the record was written: 37 of 312 exact background calls. INFERENCE: sessions ended before the notice arrived, or the model read the output file only.
- A background call that was stopped or killed: 4 notices (`killed` 3, `stopped` 1; the `stopped` text says the shell did not finish before the previous session ended).
- A hook or the auto-mode classifier refused the call: 28 background and 4 foreground calls came back as errors. They did not run, so S2 ignores them correctly.
- S2 reads transcripts of the main session and its subagents. A worker's own transcript must be discoverable from the worktree path; see `_audited_transcripts` (`audit:654`). 2 "evidence unavailable" S2 fails in other repos came from a malformed Edit row (`missing file_path`), not from test runs.

### 1.7 Cost of reruns (FACT, counts)

- 948 record outputs in transcripts (227 in this repo's sessions, 721 in other repos' sessions), against 775 stored records (199 and 576). The store keeps one file per commit, so a failed record is replaced when the same commit is audited again.
- In this repo's sessions: 67 failed outputs, 15 with S2 failed, 12 of those 15 with L4 also failed. L4 fails when the done report says the tests passed and S2 says they did not run (`auditor-brief.md`, L4).
- INFERENCE: each S2 fail on a correct run costs one suite run (about 10 minutes in the issue text; 66 calls here passed 600 s) or an owner override.

### 1.8 Options that let a passing background run count: summary (unranked)

| Option | Case | What it would stop catching |
|---|---|---|
| A1 `&&` chain with the declared command as a segment | extra step | a chain that does more than test after the tests (needs "nothing after") |
| A2 allowlist of steps before | extra step | nothing for tests; new list |
| A3 name the refused call | all | nothing; no rerun saved |
| B2 read `backgroundTaskId`, demand the notice | moved foreground | nothing; adds fails for moved calls with no notice |
| C1 one documented form | long run | nothing; depends on the habit |
| C3 wrapper writes tree hash and exit code | all | nothing; adds a proof of the tested tree; new code |
| D1, D2 accept redirect or `;` with an exit 0 notice | tail forms | nothing about success |
| E1 S2 becomes a warning and L4 judges | all | S2 no longer blocks a PR with no passing run at all; the auditor judges from the same digest |
| E2 accept the declared command as CI proof (PR check runs) | all | needs CI; this repo has none (see `orca-inbox-tests.md`) |

Bodies for E1 and E2:
- E1. S2 stops blocking and prints a warning; L4 still compares the done report with the digest. Stops catching: a PR with no passing run at all is no longer blocked by a script; only the auditor's judgement is left, and L4 fails today mostly by repeating S2.
- E2. The declared command runs in CI, and S2 reads the PR check result for the pushed commit. Stops catching: nothing about test success; it needs a CI pipeline (this repo has none) and removes the transcript form problem. A session could still skip local tests.

### 1.9 Counts used above (FACT)

Declared-command calls in transcripts of this repo's worktrees (5,104 files, 213 files with a call, dates 2026-10-21 to 2026-11-17), deduplicated by tool-use id: 439.

| Group | Calls | Exit 0 | Failed or killed | No notice or result |
|---|---|---|---|---|
| background, exact form | 312 | 256 | 19 | 37 |
| background, refused form | 22 | 15 | 1 | 6 |
| foreground moved, exact form | 56 | 51 | 2 | 3 |
| foreground moved, refused form | 23 | 15 | 3 | 5 |
| foreground, not moved | 26 | 17 | 9 (5 `command-failed` lines, 4 errors) | 0 |

(The foreground rows read the stdout of the result; "exit 0" there means no error and no `command-failed` line. Of the 17 exit-0 plain foreground calls, 1 has an accepted form, 4 have a refused form and 12 are stale or edited copies. Of the 15 exit-0 moved calls with a refused row, 12 have a refused form and 3 are stale copies. So exit-0 calls refused by S2: 15 + 12 + 4 = 31 on form, plus 15 stale copies (12 + 3) = 46. Short answer item 4 uses these numbers.)

## 2. Per-check analysis

Sample: 775 stored records (199 for this repo, 576 for other repos of the owner) and 96 pre-dispatch records. Fails are counted per record item. A record can fail several items. FALSE = the work was correct and only the evidence form (or a check limit) was wrong. SETUP = the repo has no ledger or declaration, so the check cannot judge. REAL = a rule was broken.

### 2.1 Table

| Check | Purpose and rule | Fails (this repo / other / total) | Looks false (method) | Owner overrides (12 matched PRs) | Real catch in the records |
|---|---|---|---|---|---|
| S1 | no edit in the main checkout (section 10) | 13 / 2 / 15 | 13 of 13 this repo: every path is a memory note (evidence text); exempt since PR 255. The 2 other are unreadable rows (SETUP) | 6 | none left; all fails were memory notes |
| S2 | declared test command ran after last edit and passed (section 6, Test command) | 4 / 154 / 158 | this repo: 2 form (a chain, a redirect), 1 run unfinished at audit, 1 undetermined. Other: 133 SETUP (no declaration); 21 declared fails not classified | 2 (both on 2026-11-17) | none proven |
| S3 | no finding left open in the ledger (section 6 ledger) | 0 / 3 / 3 | 2 SETUP (no ledger) | 0 | 1 (open findings with no status) |
| S4 | each Blocking code-review finding has a verdict by a Sonnet subagent (section 6 verifier) | 0 / 3 / 3 | 2 SETUP | 0 | 1 (finding with no verdict) |
| S5 | round caps, extensions and size approvals backed by real owner input (section 6, caps) | 2 / 11 / 13 | 3 quote not found in real user input, 1 size question did not name the size; 3 SETUP | 2 | 6 rounds past the cap |
| S6 | the phase commit reviewed by the final round is an ancestor of HEAD (section 6 step 3) | 3 / 6 / 9 | 6 "not an ancestor" after a rebase with no new phase-commit event (form, INFERENCE); 2 SETUP | 0 | 1 patch-id differs (content changed after the final review) |
| XC | reviewers and verifiers are Sonnet subagents that started after the previous round (section 6 roles, section 9) | 4 / 12 / 16 | 5 placeholder ids "pending" (fixed later by write-time validation); 2 SETUP; 2 unreadable rows | 0 | 7 "started before the previous round" |
| S7 | every subagent and worker runs on a Sonnet model (section 9) | 3 / 7 / 10 | 5 "no assistant row with a model" or unreadable (not a violation) | 1 | 5 ran on Haiku or Opus |
| S8 | conventional commit headers, no attribution line (section 8) | 0 / 26 / 26 | 26 of 26 other repos: 17 records show merge-commit headers (20 of 26 records date before the merge exemption of #287), 10 show `revert` headers, others ticket-style or comma-scope headers; 3 records have a human co-author line (a record may match several classes, so the sub-counts add to more than 26) | 0 | none |
| S9 | no recursive `rm`, no `docker prune`, test runners with at most 2 workers (sections 13, 14, 15) | 19 / 77 / 96 | by evidence row (103 unique rows): 61 "cannot split the command", 50 of those commands ran fine (not a violation); 15 flag-value rows (a value like `2` followed by a backtick or colon) | 8 | 17 of 27 `rm` rows use `rm -r` as a command word (5 this repo, 12 other); 5 other-repo `rm` rows were denied before running |
| S10 | each Blocking finding quotes a line that reviewers wrote (section 7 plan-review rule) | 0 / 1 / 1 | 0 of 1 false; 1 not classifiable as false: 9 linked findings have no quote (INFERENCE: they may predate the quote rule; the record has no date for the finding) | 0 | none proven (9 unquoted linked findings; they may predate the quote rule) |
| L1 | finding types follow the section 6 evidence rules | 6 / 10 / 16 | judgement; see 2.3 | 0 | reasons with a quote missing (pre-dispatch 8 times) |
| L2 | each review phase ran on the right diff | 3 / 10 / 13 | 3 of 3 this repo cascade from S6 or XC ("evidence unavailable") | 1 | none separate from S6 and XC |
| L3 | the done report lists the deferred Minor findings | 0 / 10 / 10 | 0 of 10 false; 8 real (the report omits 1 to about 20 deferred findings of the ledger, read from the auditor text); 2 not classifiable (no ledger to compare) | 0 | 8 |
| L4 | no claim in the done report contradicts the evidence | 5 / 23 / 28 | 4 of 5 this repo, and 10 of 23 other, only repeat an S2 fail | 3 | 1 report claimed the full command while the runs lacked a folder |
| L5 | the small-task estimate was right | 8 / 10 / 18 | 4 of 8 this repo are 74 to 147 changed lines, which pass the current 150-line rule; the brief then said about 50 | 0 | 4 are 167 to 331 lines |
| L6 | a ticket has its spec link and plan-review rounds | 0 / 18 / 18 | 4 of 18 look false (the report says the plan-review ran, but its evidence is outside the ledger and has no link event: another branch, issue comments, a local spec); 9 real (the report itself says it took the small-task path or ran no plan-review, which section 7 forbids for a ticket); 5 not classifiable (no ledger, a research ticket, or no statement in the report about plan-review) | 0 | 9 |
| pre-dispatch (96 records) | S3, S5, S7, XC, S10, L1 before dispatch | 17 records, 24 item fails: L1 10, S5 4 (2 SETUP), XC 4, S3 3, S7 3 | S3 "no round event" on a research-only map (issue 773): 1; XC "not a subagent of an audited transcript" 2 (cause not read); 2 SETUP | not measured | L1 8 (Blocking findings with no quote), S7 3, S5 2 (past cap) |

(Overrides: the 12 PRs and their failed items are listed in 2.2. A PR with several failed items is counted once per item. S2 counts: PRs 739 and 797.)

### 2.2 Owner overrides (FACT for counts, INFERENCE for the meaning)

- Method 1: a PR whose head commit has a stored record that failed. The gate hook denies `gh pr create` without a passing record, so such a PR was opened by a path that skips it. Result: of 184 PRs created since 2026-10-26, 26 had a failed last record at the PR head (14 percent); 156 had a pass; 2 had no record.
- Method 2: a `gh pr create` command that the owner typed with the `!` prefix, found in transcripts (`<bash-input>` rows), joined to a PR created within 10 minutes. Result: 17 such commands in this repo's sessions; 12 matched a PR with a failed record, 2 matched no record (before the gate), 1 matched no PR. So the lower bound for overrides is 12 and the upper bound is 26. The other 14 fails may be owner commands of another form, or PRs from before the gate worked (the early ones are from 2026-10-26 to 2026-10-28).
- In other repos' transcripts, 132 owner `!` `gh pr create` commands exist. They were not joined to records (no PR data); they are not counted as overrides.
- Failed items of the 12 matched PRs: S9 8 (PRs 175, 176, 193, 194, 200, 208, 385, 450), S1 6 (175, 176, 193, 194, 200, 208), L4 3 (194, 542, 797), S5 2 (193, 542), S2 2 (739, 797), L2 1 (194), S7 1 (584).
- INFERENCE: the 6 early overrides (2026-10-26 to 2026-10-28) are the S1 memory-note fails and S9 parser fails; both classes are now fixed or reduced. The recent overrides (2026-11-09 and later: 385, 450, 542, 584, 739, 797) are S9 (2), S5 and L4 (1), S7 (1) and S2 (2). The two latest are S2.

### 2.3 Notes per check

- **S1.** The 13 fails of this repo are all edits to memory notes in the user's config folder, dated 2026-10-26 to 2026-10-28. `_is_memory_note` (`audit:727`) exempts them. No S1 fail since. Options: (a) status quo (the memory exemption stays); (b) also exempt other non-repo paths of the user's config folder, which stops catching an edit to a tracked config file outside a worktree.
- **S2.** See Section 1. The 133 "no declaration" fails are repos that the workflow touched without a `### Test command` section. Options: (a) keep: the audit demands a declaration; (b) make "no declaration" a SETUP note that does not block; (c) keep and add the declaration at setup time. What (b) stops catching: a repo that never declares tests would pass S2 with no test proof.
- **S3, S4, S5, S6, XC, S10 (ledger checks).** Most of their fails in other repos are "no ledger" or "no round event" (SETUP). In this repo they are 0 to 4 each. Real catches exist for rounds past a cap (6), reviewers that started before the previous round (8) and a finding with no verdict (1). S3, S4, S5, XC, S10, L2, L3, L6 and the pre-dispatch items are not controversial here (few or no false fails, or the fails are setup gaps), so they get no options, except the L6 option below. Option for S6 (status quo: the new phase-commit event is required): after a rebase could re-derive the phase commit by patch-id without a new event. What it stops catching: a rebase that changed the content after the final review (1 real case in the records, caught by the patch-id test).
- **S7.** Real catches: 5 runs on Haiku or Opus (INFERENCE: some come from a subagent type whose default model is not Sonnet). Options: (a) status quo; (b) make "no assistant row with a model" a note. What the note stops catching: a subagent with no model row.
- **S8.** All 26 fails are in other repos. Merge commits with two parents are exempt since #287 (`audit:330-334`). Remaining fails are `revert` (the type list at `audit:81` has no `revert`), ticket-style headers and a scope with a comma (the pattern at `audit:82` allows no comma). Options: (a) status quo; (b) add `revert` and allow a comma in the scope (stops catching: nothing about attribution); (c) apply S8 only to the repo's own commit style. What the last stops catching: a repo with no rule gets no check.
- **S9.** The largest single source of false fails by count. 61 evidence rows say "evidence unavailable: cannot split the command"; for 50 of them the shell ran the command fine (6 this repo and 3 other were denied by a hook, 2 errored). FACT: that text means the audit's parser failed, not that a command was bad. 15 more rows are flag-value text. The 17 `rm -r` command words (section 13 forbids them) are a true catch of a rule break, even when a hook denied some of them. Options: (a) keep; (b) make "cannot split" a warning and keep real hits as fails (stops catching: a destructive command hidden in text the parser cannot read; mitigation: the hook that denies such a call at run time already exists, `redact_pre` and the PR gate); (c) require that the call actually ran (the result is not a hook denial): 5 of the `rm` rows in other repos were denied before they ran.
- **L1.** The auditor fails a Minor finding that has the evidence of a Blocking one, although the section 6 text says "The loop session decides the final type". Options: (a) status quo; (b) restrict L1 to the written evidence rules and not to type judgement. What the second stops catching: a Blocking bug filed as Minor to avoid a verifier.
- **L4.** It repeats S2: 4 of 5 fails here and 10 of 23 in other repos restate an S2 fail. If S2 is fixed, these go away. The one real catch is a claim about the full declared command that the runs did not support.
- **L5.** The brief said about 50 lines for part of the period and CLAUDE.md now says about 150. Four of the eight fails here are 74 to 147 lines. Options: (a) status quo (the brief holds its own number; `auditor-brief.md` hard-codes "about 150" today, so it can drift again); (b) the brief reads the number from CLAUDE.md, which adds drift protection and stops catching nothing; (c) make L5 a note instead of a fail (stops catching: an oversized task on the small-task path).
- **L6, L3, S10.** Classified from the auditor text in the record (29 fails, all in other repos). L6 (18): 9 real, 4 look false, 5 not classifiable. L3 (10): 8 real, 0 false, 2 not classifiable because no ledger exists. S10 (1): 0 false, 1 not classifiable as false. An option for L6: let the session write the link event to the plan-review ledger; what that stops catching: nothing, it only fixes the 4 form cases.
- **Pre-dispatch.** One structural false fail: S3 on a map with no spec yet (issue 773). Another: "no ledger" on a fresh repo. The L1 and S7 fails match real rule breaks.

### 2.4 How other agent workflows check evidence (FACT from `agent-workflow-comparison.md`)

That document found that, in the pages read, no public workflow keeps an audit record file, and that vendors use one or two human gates (a plan approval or the PR) and PR check runs. So none of those sources offers a precedent for a transcript-based test proof. The nearest precedent is the PR check run (CI). This repo has no CI today (`orca-inbox-tests.md`).

## Method and sample sizes

- Audit code: `hooks/workflow-audit/audit` and the tests `test_*.py`, read for what each check does. Line numbers refer to this worktree.
- Stored records: the runtime folder of the audit holds one JSON file per audited commit (`<sha>.json`) and one per session for pre-dispatch. FACT: 871 files = 775 commit records (199 this repo, 576 other repos; 2026-10-26 to 2026-11-17) + 96 pre-dispatch records. A new record of the same commit replaces the old one.
- Record outputs in transcripts: 948 outputs of `audit record` (a block that has `S1` and `result` lines and no digest line), over 20,280 transcript files. This is the only view of superseded records.
- Declared-command calls: 439 deduplicated Bash calls that hold the declared block (matched on a fixed text), in 5,104 transcript files of this repo's worktrees. Each call was classified by prefix, suffix, background flag, tool result form and notices with the same tool-use id (notices read from every transcript file, so a subagent run reported in the main transcript is joined). A call is "exact form" when S2's own rules would accept the text (a plain `cd` to the worktree, the redact suffix on foreground only, a block equal to some committed declaration). The `cd` target was not resolved; we assumed it was the worktree.
- Declarations: 11 versions found in the git history of the declaring files.
- Overrides: methods 1 and 2 in 2.2. PR data from `gh pr list` (226 PRs of this repo, read-only). Records joined to PRs by branch name and by the last record before the PR creation time.
- S9 rows: each evidence line (file and row) was opened, and the tool result checked for a hook denial or an error. `rm` text was split into "command word" and "text inside another command" by a regular expression (it may miss forms; counts are approximate).
- False fail judgement: by evidence text and path patterns for S1, S8, S7, S9, S5, S6, XC; by transcript for S2 of this repo (4 of 4 looked at; 1 undetermined); by evidence text of the auditor for L items (the L3, L6 and S10 sample is 29 of 29 fails, classified from the record text alone; `.ledger.txt` and `.sessions.txt` side files are not in the store, which holds `ledger-*.jsonl` files). Other repos' S2 declared fails (21) were not classified: their declared commands differ and their transcripts were not scanned for them.

## Gaps and open questions

1. The record store keeps the last record per commit. Fixed fails are invisible except through the 948 transcript outputs, which do not give the commit.
2. The override count is a range, 12 to 26. A PR can also be created before the gate hook worked or by a form the transcript scan did not match.
3. "Looks false" is our reading of evidence text. A check could fail correctly for a reason that is not in its evidence line.
4. The 22 "stale or edited" copies of the declared command and the 16 "other prefix" calls were not read one by one.
5. UNTESTED: that a test row shaped like a moved call (partial stdout plus `backgroundTaskId`) passes S2 in the test harness. The code path and 10 record joins say it does; a one-case test would settle it.
6. UNTESTED: what the harness writes to the task output file, and whether the exit code can be read from it.
7. The pre-dispatch gate cannot be overridden by a PR command; how the owner overrides it, if at all, was not measured.
8. Other repos: 576 records exist but only counts of fails are used. Whether their false fails match this repo's classes is open.

## Sources

- `hooks/workflow-audit/audit` (S2 at lines 842-938, S9 at 1966-2075, S8 at 318-384, ledger checks at 1507-1908, record at 2149-2300).
- `hooks/workflow-audit/test_transcripts.py` (S2 tests at 519-720), `audit_support.py`.
- `hooks/workflow-audit/auditor-brief.md` (L1 to L6, owner `!` test runs, pre-dispatch variant).
- `CLAUDE.md` sections 6, 7, 8 (the rules the checks enforce).
- Issues 729, 773, 787, 796, 755, 756, 799 (read with `gh`, read-only).
- `docs/research/agent-workflow-comparison.md`, `docs/research/orca-inbox-tests.md` (prior S2 reading; this document adds counts, the moved-call data and the override method).
- Local data: the audit runtime record folder and the Claude Code session transcripts of this machine (counts only).
