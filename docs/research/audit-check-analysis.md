# Workflow audit checks: false fails, background test runs and owner overrides

Question (issue 799): which checks of the workflow audit (`hooks/workflow-audit`) fail when the work was correct, how often does the owner override a failed audit, and what does each check protect? Owner priority (the owner's comment on issue 799, 2026-11-17): "let the tests run in the background without failing the audit".

Date of reading: 2026-11-17. Marks: **FACT** = read from code, a test, a stored record, or counted by a method named in the text. **INFERENCE** = our reading. **UNTESTED** = not run. No audit code was changed. Transcript text is not quoted: only counts are given.

Terms. S1 to S10 are checks that the `audit` script computes. XC is the cross-check of reviewer and verifier agents. L1 to L6 are items that an auditor subagent judges from a digest. The pre-dispatch variant is the shorter audit that runs before the first worker dispatch. S2 is the check "the declared test command ran after the last edit and passed".

## Short answer

Verdict on the main question (background test runs and S2), FACT:
- S2 refuses a passing run when the call holds more than the declared command: an extra step in an `&&` chain, a redirect (`2>&1`, `> file`), a `;` instead of `&&`, a pipe, or a copy of the declared block that differs from the one at HEAD.
- S2 accepts wrongly a foreground call that the harness moved to the background before it finished: it passes on the partial output and never reads the later exit code.
- A plain `run_in_background` call of the exact declared command (with or without a `cd <worktree> && ` prefix) passes when its task notice says exit code 0.

Findings:
1. FACT: S2 matches the call text to the declared text exactly (`hooks/workflow-audit/audit:890-920`). Issue 796 is real; no test names a `git ... &&` prefix (see 1.2).
2. FACT: issue 729 describes a fail for a call moved to the background; the code and the records show a pass, sometimes a false one (see 1.3).
3. FACT: moved calls are common: 79 of 105 foreground declared-command calls (see 1.9).
4. FACT: exit-0 runs refused by S2 on form: 31, and 15 more as stale copies (see 1.9).
5. FACT: in this repo S2 failed in 4 of 199 stored records; most S2 fails in the store (133 of 158) are repos with no declared test command, a setup gap (see 2.1).
6. FACT: the cost shows more in reruns than in stored fails: 948 audit outputs in transcripts against 775 stored records (see 1.7).
7. FACT: overrides: 26 of 184 PRs had a failed record at the head; 12 match an owner `!` `gh pr create` (see 2.2).
8. FACT: S1 had 13 false fails (memory-note edits, now exempt); S9 had parser fails and 17 real `rm -r` rows (see 2.1).
9. INFERENCE: most false fails by count: S2 (setup gap and form), S9 (parser limit), S8 (other repos' commit styles), L5 (rule drift).
10. Limits: the store keeps the last record per commit; the override count is a range; other repos' transcripts were not classified (see Method).

## 1. S2 and background runs

### 1.1 What S2 does today (FACT)

- The declared command is the one fenced block of the one `### Test command` section in `.claude/CLAUDE.md`, `CLAUDE.md` or `AGENTS.md` at HEAD (`audit:842-855`). Zero or two sections fail S2. The value `none` passes.
- A call is a candidate when its text contains the declared command (`audit:920`). It counts as a run when `normalised(call) == declared` (`audit:890-905`).
- `normalised`: strip a leading `cd <path> && ` when the path resolves to the worktree (`CD_PREFIX`, `audit:122`, matched at the start only, `audit:892`). With no such prefix, the call row's cwd must be inside the worktree. A foreground call may end with the redact suffix ` || echo command-failed`, stacked any number of times (`audit:902-903`); a background call may not.
- All runs must come after the last Edit, Write or NotebookEdit inside the worktree (`audit:921-925`). A Bash-made file write is not an edit for S2. One passing run is enough (`audit:932-933`).
- Background run (`run_in_background: true`): passes only when a `<task-notification>` with the same `tool-use-id` says `completed` and its summary ends with `(exit code 0)`; every notification of that id must agree (`audit:864-877`, `audit:927-929`). A subagent's background run may be reported in the main transcript.
- Foreground run: passes when the result is not an error, the row has one stdout, and the last stdout line is not `command-failed` (`audit:906-913`). The exit code is never read.
- The fail text has three forms: "did not run", "ran only before the last edit", "ran after the last edit but failed or did not finish" (`audit:935-938`). "Did not run" does not say why a call was refused (issue 796).

### 1.2 Case A: background call with the declared command plus another step (issue 796)

- What S2 does: `git commit ... && cd W && <cmd>` has no `cd` prefix at the start, so the text stays whole and differs from the declared text. `cd W && git log -1 && <cmd>` loses only the `cd` prefix, and `git log -1 && <cmd>` differs too. Fail text: "did not run" (`audit:892-905`, `audit:920`).
- Test: `test_a_filtered_or_piped_run_is_not_the_declared_command` (`test_transcripts.py:657`) pins `| tail`, extra arguments, `2>&1`, `cd /other && ...` and `echo ...`. No test names a `git ... &&` step before the command or after a correct `cd`; the behavior follows the same equality line.
- Frequency: see 1.9. One stored record (PR 797, S2 and L4 failed) is this case: two background runs with `cd W && <other step> && <cmd>` and exit code 0 (matched by time and by the L4 evidence text).
- Options:
  - A1. Accept the declared command as one segment of an `&&`-only chain. If the whole chain exits 0, every segment ran and passed. Needs the audit's command splitter (`split_command`, `audit:2668`) and a check that no `cd` moves away from the worktree. Stops catching: nothing about test success; the call no longer proves it was "just the tests", and a segment after the tests (`<cmd> && sed -i ...`) would count unless segments after the declared command are refused.
  - A2. As A1 but only an allowlist before the declared command (`cd`, `git log`, `git status`, `git commit`, `git add`). Stops catching: the same as A1 for other steps. Cost: a list to maintain.
  - A3. Name the closest refused call in the fail text (second direction of issue 796). Stops catching: nothing. Does not remove the rerun; it makes the cause visible.

### 1.3 Case B: foreground call moved to the background by the harness

- Forms (FACT): the first tool result carries partial stdout and `toolUseResult.backgroundTaskId` with `timedOutAfterMs` (600000 or 120000), or the text "Command was moved to the background (ID: ...)" with `backgroundedToDeliverMessage: true` (a message arrived). The `tool_use` input has no `run_in_background`. The exit code arrives later in a `<task-notification>` with the same `tool-use-id`.
- What S2 does (FACT, code): `background` is set only from `run_in_background is True` (`audit:558`), so the call is read as foreground. `last_lines` holds the partial stdout (or an empty string), not `None`, so `foreground_outcome` returns True unless the output ends with `command-failed` or the result is an error (`audit:906-913`). S2 passes at once and never reads the notification. No code or test uses `backgroundTaskId`, `timedOutAfterMs` or "moved to the background".
- Result (FACT): S2 passed some moved runs that later failed, were killed or never reported (see 1.9). Ten branch records have only moved runs as passing runs, and S2 passed on all ten. This does not match the failure that issue 729 describes. INFERENCE: that failure may come from another cause in its session (a pipe, a redirect or a chain, as in case A); we did not find that session.
- Options:
  - B1. No change. Stops catching: nothing new; the false passes stay.
  - B2. Read `backgroundTaskId` in the tool result row; when set, treat the call as a background run and demand a notice with exit code 0 (the same `_notification_exit`). Same as option B of `orca-inbox-tests.md`. Stops catching: nothing; closes the false pass. Adds a fail when the notice is missing, so the session must wait for the notice (section 7 already asks workers to). See the UNTESTED gaps 5 and 6.
  - B3. As B2, and also accept the task output file when it holds the declared command's exit code. Not supported today: the output file holds stdout, not the exit code. See the UNTESTED gap 6.

### 1.4 Case C: run longer than the 600 s Bash limit (issue 729)

- FACT: calls that hit the 600 s foreground limit are routine in this sample (see 1.9). Background runs have no such limit, and S2 accepts them when the call is exact. A foreground call that crosses 600 s behaves as in case B.
- FACT: some exact background calls have no notice at all (see 1.9). INFERENCE: the session ended, was cut, or read the output file instead of waiting; a notice only arrives while the session still runs. S2 fails these unless another run passes.
- Options:
  - C1. Document one supported form: `run_in_background: true`, exact command text, then a blocking wait for the notice. It works today. Same as option A of `orca-inbox-tests.md`. Stops catching: nothing. It relies on a habit that most foreground calls do not show (see 1.9).
  - C2. C1 plus B2, so the habit is not needed. Stops catching: nothing.
  - C3. A wrapper script as the one declared command that writes `<tree hash> <exit code>` to a file in the audit runtime folder, and S2 reads it for the pushed tree. Stops catching: nothing; adds proof that the tested tree is the pushed tree (S2 today only compares with the last Edit call; Bash writes are invisible). Cost: new code and tests; the file is written by the session, so it is a claim unless only the wrapper can write the runtime folder (UNTESTED).

### 1.5 Case D: redirects, `;`, pipes, redact suffix, stale copy, other

| Form | S2 result | Pinned by test |
|---|---|---|
| `... 2>&1` after the command | refused (text differs) | `test_transcripts.py:657` |
| `... > file` after the command | refused | not pinned (UNTESTED) |
| `cd W; <cmd>` (semicolon) | refused; `CD_PREFIX` needs `&&` (`audit:122`) | none (UNTESTED) |
| `\| tail`, other pipe | refused | `test_transcripts.py:657` |
| ` \|\| echo command-failed` on a foreground call | accepted; a failing stdout line fails it | `test_transcripts.py:582-603` |
| same suffix on a background call | refused: the suffix hides the exit code | `test_transcripts.py:634` |
| a copy of the declared block that is not the one at HEAD | refused | none by name |
| other prefix (a variable, `source`, an `export`) | refused | none by name |
| owner `!` run | invisible: the transcript has no tool result | `auditor-brief.md:61` |
| Edit or Write in the worktree after the run, even a Markdown file | "ran only before the last edit" | `test_transcripts.py:533-558` |
| declaration changed by a rebase onto the base branch | the HEAD text differs from the text that was run | none |

Counts per form are in 1.9. Notes:
- FACT: the stale or edited copies are not equal to any committed declaration. INFERENCE: most are partial runs (a subset of folders) or runs of an older declaration; S2 is right to refuse a partial run. We did not read them one by one. The declaration changed 11 times between 2026-10-23 and 2026-11-16 (git log of the file).
- FACT: the declaration is read at HEAD, so a rebase that adds a folder to the declaration makes earlier runs stale. One L4 fail in this repo shows a done report that claimed the full command while the runs lacked a folder added on the base branch: a real catch (see 2.3, L4).
- Options:
  - D1. Accept `2>&1` and `> file` after the command when the call is a background run with an exit 0 notice (the exit code is the command's own). Stops catching: nothing about success. A redirect hides output from the transcript; S2 does not need it.
  - D2. Treat `;` like `&&` when the declared command is last (the exit code is the command's). Stops catching: nothing about the declared command's result.
  - D3. Refuse pipes always (today). A pipe's exit code is the last command's unless `pipefail` is set, so `| tail` can hide a failure. Stops catching: nothing new; it keeps refusing passing runs that use a pipe.
  - D4. Name the refused form in the fail text (extra step before, extra step after, redirect, pipe, stale copy, outside worktree). Stops catching: nothing. Cost: a few lines and tests.

### 1.6 Case E: other ways a passing run fails S2 (FACT)

- A background call with no notice before the record was written (see 1.9). INFERENCE: sessions ended before the notice arrived, or the model read the output file only.
- A background call that was stopped or killed: 4 notices (`killed` 3, `stopped` 1; the `stopped` text says the shell did not finish before the previous session ended).
- A hook or the auto-mode classifier refused the call: 28 background and 4 foreground calls came back as errors. They did not run, so S2 ignores them correctly.
- S2 reads transcripts of the main session and its subagents. A worker's own transcript must be discoverable from the worktree path (`_audited_transcripts`, `audit:654`). 2 "evidence unavailable" S2 fails in other repos came from a malformed Edit row (`missing file_path`), not from test runs.
- Options:
  - E1. S2 stops blocking and prints a warning; L4 still compares the done report with the digest. Stops catching: a PR with no passing run at all is no longer blocked by a script; only the auditor's judgement is left, and L4 fails today mostly by repeating S2.
  - E2. The declared command runs in CI, and S2 reads the PR check result for the pushed commit. Stops catching: nothing about test success; removes the transcript form problem. Cost: a CI pipeline (this repo has none); a session could still skip local tests.

### 1.7 Cost of reruns (FACT, counts)

- 948 record outputs in transcripts (227 in this repo's sessions, 721 in other repos' sessions), against 775 stored records (199 and 576). The store keeps one file per commit, so a failed record is replaced when the same commit is audited again.
- In this repo's sessions: 67 failed outputs, 15 with S2 failed, 12 of those 15 with L4 also failed. L4 fails when the done report says the tests passed and S2 says they did not run (`auditor-brief.md`, L4).
- INFERENCE: each S2 fail on a correct run costs one suite run (about 10 minutes in the issue text) or an owner override.

### 1.8 General options (root causes)

- G1. Root cause of A1, A2, D1, D2 and D4, the exact text match: a shell-parse rule. Accept a call where the declared command is a simple command in an `&&` or `;` chain, nothing after it writes files, exit 0 is proven, and the cwd is the worktree. Stops catching: nothing about test success; refuses a chain whose later segment changes files. Cost: one parser (it could be shared with S9) plus tests for nested and quoted forms.
- G2. Root cause of B2, C1 and C2, the split between foreground and background reading: one outcome resolver. Every call resolves to one exit code from its result row or from the matching task notification, whatever its form. Stops catching: nothing. Cost: one function replaces the split.
- G3. Root cause of the S9 "cannot split" false fails: replace the hand-written splitter with a real shell parser. If a parse error then passes (fail open), S9 stops catching destructive commands it cannot parse, which weakens a safety check. The alternative is to keep failing closed on parse errors. Cost: a parser dependency or a larger own parser, and tests.
- G4. Root cause of the "edits before the run" heuristic: bind the test evidence to the tree. Record the tree hash at run time (or in a pre-push hook) and compare it with the pushed tree. Stops catching: nothing; also sees Bash-made writes. Cost: a hook and a store.

Index of all options (bodies are in the section named):

| Id | Name | Section |
|---|---|---|
| A1 | `&&` chain with the declared command as a segment | 1.2 |
| A2 | allowlist of steps before the command | 1.2 |
| A3 | name the refused call in the fail text | 1.2 |
| B1 | no change for moved calls | 1.3 |
| B2 | read `backgroundTaskId`, demand the notice | 1.3 |
| B3 | B2 plus the task output file | 1.3 |
| C1 | one documented background form | 1.4 |
| C2 | C1 plus B2 | 1.4 |
| C3 | wrapper writes tree hash and exit code | 1.4 |
| D1 | accept redirect with an exit 0 notice | 1.5 |
| D2 | accept `;` with the declared command last | 1.5 |
| D3 | refuse pipes | 1.5 |
| D4 | name the refused form | 1.5 |
| E1 | S2 becomes a warning | 1.6 |
| E2 | CI result as test proof | 1.6 |
| G1 | shell-parse rule | 1.8 |
| G2 | one outcome resolver | 1.8 |
| G3 | real shell parser for S9 | 1.8 |
| G4 | bind the evidence to the tree hash | 1.8 |

### 1.9 Counts for section 1 (FACT)

Declared-command calls in transcripts of this repo's worktrees (5,104 files, 213 files with a call, dates 2026-10-21 to 2026-11-17), deduplicated by tool-use id: 439 (334 background, 105 foreground).

| Group | Calls | Exit 0 | Failed or killed | No notice or result |
|---|---|---|---|---|
| background, exact form | 312 | 256 | 19 | 37 |
| background, refused form | 22 | 15 | 1 | 6 |
| foreground moved, exact form | 56 | 51 | 2 | 3 |
| foreground moved, refused form | 23 | 15 | 3 | 5 |
| foreground, not moved | 26 | 17 | 9 (5 `command-failed` lines, 4 errors) | 0 |
| refused exit-0: form 31, stale copy 15, total 46 | | | | |

Reading: "exit 0" for foreground rows means no error and no `command-failed` line. Moved calls: 79 (66 at 600 s, 11 at 120 s, 2 because a message arrived). Of the 56 moved calls of an accepted form, S2 passed all 56 on partial output; the notice says 51 exit 0, 1 failed, 1 killed, 3 none, so 5 passes had no proof.

Calls per form (of 439), and exit-0 calls that S2 refused:

| Form | Calls | Exit-0 refused |
|---|---|---|
| extra step before the command | 24 (13 background, 9 moved, 2 foreground) | 14 |
| `2>&1` or a redirect after the command | 46 (41 `2>&1`, 5 redirect); 18 are exact except for that tail | 13 |
| `cd W; <cmd>` | 10 | 4 |
| pipe | 0 | 0 |
| redact suffix on a foreground call (accepted) | 5 | n/a |
| redact suffix on a background call | 0 | 0 |
| copy of the declared block not at HEAD | 22 (19 foreground, 3 moved) | 15 |
| other prefix (a variable, `source`, an `export`) | 16 | not counted |
| owner `!` test run | 0 found in transcripts | n/a |

("Extra step before" includes the 16 "other prefix" calls; the form counts overlap.)

## 2. Per-check analysis

Sample: 775 stored records (199 for this repo, 576 for other repos of the owner) and 96 pre-dispatch records. Fails are counted per record item; a record can fail several items. FALSE = the work was correct and only the evidence form (or a check limit) was wrong. SETUP = the repo has no ledger or declaration, so the check cannot judge. REAL = a rule was broken. Notes per check are in 2.3; owner overrides per check are in 2.2.

### 2.1 Table

| Check | Purpose and rule | Fails (this repo / other / total) | Looks false | Real catch |
|---|---|---|---|---|
| S1 | no edit in the main checkout (section 10) | 13 / 2 / 15 | 13 (memory notes); 2 unreadable | none left |
| S2 | declared test command ran after last edit and passed (section 6, Test command) | 4 / 154 / 158 | this repo 2 of 4 (form), 1 unfinished, 1 undetermined; other 133 SETUP, 21 not classified | none proven |
| S3 | no finding left open in the ledger (section 6 ledger) | 0 / 3 / 3 | 2 SETUP | 1 |
| S4 | each Blocking code-review finding has a Sonnet verdict (section 6 verifier) | 0 / 3 / 3 | 2 SETUP | 1 |
| S5 | round caps, extensions, size approvals backed by real owner input (section 6 caps) | 2 / 11 / 13 | 4 form, 3 SETUP | 6 |
| S6 | the reviewed phase commit is an ancestor of HEAD (section 6 step 3) | 3 / 6 / 9 | 6 form (INFERENCE), 2 SETUP | 1 |
| XC | reviewers and verifiers are Sonnet subagents started after the previous round (section 6, section 9) | 4 / 12 / 16 | 5 placeholder ids, 2 SETUP, 2 unreadable | 7 |
| S7 | every subagent and worker runs on a Sonnet model (section 9) | 3 / 7 / 10 | 5 unreadable or no model row | 5 |
| S8 | conventional commit headers, no attribution (section 8) | 0 / 26 / 26 | 26 (other repos' styles) | none |
| S9 | no recursive `rm`, no `docker prune`, runners with at most 2 workers (sections 13, 14, 15) | 19 / 77 / 96 | 61 "cannot split" rows (50 ran fine), 15 flag-value rows | 17 `rm` rows |
| S10 | each Blocking finding quotes a line that reviewers wrote (section 7) | 0 / 1 / 1 | 0 false; 1 not classifiable | none proven |
| L1 | finding types follow the section 6 evidence rules | 6 / 10 / 16 | judgement | quote missing (pre-dispatch 8) |
| L2 | each review phase ran on the right diff | 3 / 10 / 13 | 3 of 3 here cascade from S6 or XC | none separate |
| L3 | the done report lists the deferred Minor findings | 0 / 10 / 10 | 0 false; 2 not classifiable | 8 |
| L4 | no claim in the done report contradicts the evidence | 5 / 23 / 28 | 14 repeat an S2 fail | 1 |
| L5 | the small-task estimate was right | 8 / 10 / 18 | 4 of 8 here (rule drift) | 4 |
| L6 | a ticket has its spec link and plan-review rounds | 0 / 18 / 18 | 4 false, 5 not classifiable | 9 |
| pre-dispatch (96 records) | S3, S5, S7, XC, S10, L1 before dispatch | 17 records, 24 item fails | S3 on a research-only map (1), 2 SETUP, XC 2 cause not read | L1 8, S7 3, S5 2 |

### 2.2 Owner overrides (FACT for counts, INFERENCE for the meaning)

- Method 1: a PR whose head commit has a stored record that failed. The gate hook denies `gh pr create` without a passing record, so such a PR was opened by a path that skips it. Result: of 184 PRs created since 2026-10-26, 26 had a failed last record at the PR head (14 percent); 156 had a pass; 2 had no record.
- Method 2: a `gh pr create` command that the owner typed with the `!` prefix, found in transcripts (`<bash-input>` rows), joined to a PR created within 10 minutes. Result: 17 such commands in this repo's sessions; 12 matched a PR with a failed record, 2 matched no record (before the gate), 1 matched no PR. So the lower bound for overrides is 12 and the upper bound is 26. The other 14 fails may be owner commands of another form, or PRs from before the gate worked (the early ones are from 2026-10-26 to 2026-10-28).
- In other repos' transcripts, 132 owner `!` `gh pr create` commands exist. They were not joined to records (no PR data); they are not counted as overrides.
- Failed items of the 12 matched PRs (a PR with several failed items counts once per item): S9 8 (PRs 175, 176, 193, 194, 200, 208, 385, 450), S1 6 (175, 176, 193, 194, 200, 208), L4 3 (194, 542, 797), S5 2 (193, 542), S2 2 (739, 797), L2 1 (194), S7 1 (584).
- INFERENCE: the 6 early overrides (2026-10-26 to 2026-10-28) are the S1 memory-note fails and S9 parser fails; both classes are now fixed or reduced. The recent overrides (2026-11-09 and later: 385, 450, 542, 584, 739, 797) are S9 (2), S5 and L4 (1), S7 (1) and S2 (2). The two latest are S2.

### 2.3 Notes per check

- **S1.** The 13 fails of this repo are all edits to memory notes in the user's config folder, dated 2026-10-26 to 2026-10-28. `_is_memory_note` (`audit:727`) exempts them. No S1 fail since. The 2 other fails are unreadable rows (SETUP). Options: (a) status quo (the memory exemption stays); (b) also exempt other non-repo paths of the user's config folder, which stops catching an edit to a tracked config file outside a worktree.
- **S2.** See Section 1. The 133 "no declaration" fails are repos that the workflow touched without a `### Test command` section. Options: (a) status quo: the audit demands a declaration; (b) make "no declaration" a SETUP note that does not block, which stops catching a repo that never declares tests; (c) add the declaration at setup time. For this repo's 4 fails: PR 797 is case A, one redirect case is a form problem, PR 739 had a run unfinished at audit time, one is undetermined.
- **S3, S4, S5, XC, S6.** Most fails in other repos are "no ledger" or "no round event" (SETUP). In this repo they are 0 to 4 each. S5: 4 form fails (3 "quote not found in real user input", 1 size question that did not name the size), 3 SETUP, 6 real (rounds past a cap). XC: 5 placeholder reviewer ids (fixed later by write-time validation), 7 real ("started before the previous round"). S6: 6 "not an ancestor" after a rebase with no new phase-commit event (INFERENCE), 1 real patch-id difference. Option for S6 (status quo: the new phase-commit event is required): after a rebase, derive the phase commit by patch-id without a new event, which stops catching a rebase that changed content after the final review (1 real case in the records).
- **S7.** Real catches: 5 runs on Haiku or Opus (INFERENCE: some come from a subagent type whose default model is not Sonnet). Options: (a) status quo; (b) make "no assistant row with a model" a note, which stops catching a subagent with no model row.
- **S8.** All 26 fails are in other repos; 17 records show merge-commit headers (20 of 26 records date before the merge exemption of #287, `audit:330-334`), 10 show `revert` headers, others ticket-style or comma-scope headers, 3 have a human co-author line (a record may match several classes, so the sub-counts add to more than 26). Remaining fails are `revert` (the type list at `audit:81` has no `revert`), ticket-style headers and a scope with a comma (the pattern at `audit:82` allows no comma). Options: (a) status quo; (b) add `revert` and allow a comma in the scope (stops catching: nothing about attribution); (c) apply S8 only to the repo's own commit style, which gives a repo with no rule no check.
- **S9.** The largest single source of false fails by count. 61 evidence rows say "evidence unavailable: cannot split the command"; for 50 of them the shell ran the command fine (6 in this repo and 3 in other repos were denied by a hook, 2 errored). That text means the audit's parser failed, not that a command was bad. 15 more rows are flag-value text. The 17 `rm -r` command words (section 13 forbids them) are a true catch of a rule break, even when a hook denied some of them (5 rows in other repos were denied before they ran). Options: (a) status quo; (b) make "cannot split" a warning and keep real hits as fails (stops catching: a destructive command hidden in text the parser cannot read; the run-time hook that denies such calls already exists); (c) require that the call actually ran (the result is not a hook denial); (d) G3 in 1.8.
- **S10, L3, L6.** Classified from the auditor text in the record (29 fails, all in other repos, 29 of 29 read). S10 (1): 9 linked findings have no quote, which may predate the quote rule (INFERENCE; the record has no date for the finding); not classifiable as false, no real catch proven. L3 (10): 8 real (the report omits 1 to about 20 deferred findings), 2 not classifiable (no ledger). L6 (18): 4 look false (the report says the plan-review ran, but its evidence is outside the ledger with no link event: another branch, issue comments, a local spec), 9 real (the report says it took the small-task path or ran no plan-review, which section 7 forbids for a ticket), 5 not classifiable (no ledger, a research ticket, or no statement about plan-review). Option for L6: let the session write the link event to the plan-review ledger, which stops catching nothing and fixes the 4 form cases.
- **L1.** The auditor fails a Minor finding that has the evidence of a Blocking one, although the section 6 text says "The loop session decides the final type". Options: (a) status quo; (b) restrict L1 to the written evidence rules and not to type judgement, which stops catching a Blocking bug filed as Minor to avoid a verifier.
- **L2.** 3 of 3 fails here cascade from S6 or XC ("evidence unavailable").
- **L4.** It repeats S2: 4 of 5 fails here and 10 of 23 in other repos restate an S2 fail. If S2 is fixed, these go away. The one real catch is a claim about the full declared command that the runs did not support.
- **L5.** The brief said about 50 lines for part of the period and CLAUDE.md now says about 150. Four of the eight fails here are 74 to 147 lines (they pass the current rule); four are 167 to 331 lines (real). Options: (a) status quo (the brief holds its own number; `auditor-brief.md` hard-codes "about 150" today, so it can drift again); (b) the brief reads the number from CLAUDE.md, which adds drift protection and stops catching nothing; (c) make L5 a note instead of a fail, which stops catching an oversized task on the small-task path.
- **Pre-dispatch.** 17 records, 24 item fails: L1 10, S5 4 (2 SETUP), XC 4, S3 3, S7 3. One structural false fail: S3 on a map with no spec yet (issue 773). Another: "no ledger" on a fresh repo. The L1 (8 Blocking findings with no quote), S7 and S5 (past cap) fails match real rule breaks.
- No options are given for S3, S4, S5, XC, L2, L3 and the pre-dispatch items: they have few false fails or setup gaps only. S6, S7, S10 and L6 have the options or notes above.

### 2.4 How other agent workflows check evidence (FACT from `agent-workflow-comparison.md`)

That document found that, in the pages read, no public workflow keeps an audit record file, and that vendors use one or two human gates (a plan approval or the PR) and PR check runs. So none of those sources offers a precedent for a transcript-based test proof. The nearest precedent is the PR check run (CI). This repo has no CI today (`orca-inbox-tests.md`).

## Method and sample sizes

- Audit code: `hooks/workflow-audit/audit` and the tests `test_*.py`, read for what each check does. Line numbers refer to this worktree.
- Stored records: one JSON file per audited commit (`<sha>.json`) and one per session for pre-dispatch, in the audit runtime folder. 871 files = 775 commit records (199 this repo, 576 other repos; 2026-10-26 to 2026-11-17) + 96 pre-dispatch records. A new record of the same commit replaces the old one.
- Record outputs in transcripts: 948 outputs of `audit record` (a block with `S1` and `result` lines and no digest line) over 20,280 transcript files. This is the only view of superseded records.
- Declared-command calls: 439 deduplicated Bash calls that hold the declared block (matched on a fixed text), in 5,104 transcript files of this repo's worktrees. Each was classified by prefix, suffix, background flag, tool result form and notices with the same tool-use id (notices read from every transcript file, so a subagent run reported in the main transcript is joined).
- "Exact form": the text S2's own rules would accept (a plain `cd` to the worktree, the redact suffix on foreground only, a block equal to some committed declaration). The `cd` target was not resolved; we assumed it was the worktree.
- Declarations: 11 versions found in the git history of the declaring files.
- Overrides: methods 1 and 2 in 2.2. PR data from `gh pr list` (226 PRs of this repo, read-only). Records joined to PRs by branch name and by the last record before the PR creation time.
- S9 rows: each evidence line (file and row) was opened and the tool result checked for a hook denial or an error. `rm` text was split into "command word" and "text inside another command" by a regular expression (it may miss forms; counts are approximate).
- False fail judgement: by evidence text and path patterns for S1, S8, S7, S9, S5, S6, XC; by transcript for S2 of this repo (4 of 4 looked at; 1 undetermined); by the auditor's evidence text for L items (the L3, L6 and S10 sample is 29 of 29 fails, classified from the record text alone; `.ledger.txt` and `.sessions.txt` side files are not in the store, which holds `ledger-*.jsonl` files).
- Not classified: other repos' S2 declared fails (21); their declared commands differ and their transcripts were not scanned for them.

## Gaps and open questions

1. The record store keeps the last record per commit. Fixed fails are invisible except through the 948 transcript outputs, which do not give the commit.
2. The override count is a range, 12 to 26. A PR can also be created before the gate hook worked or by a form the transcript scan did not match.
3. "Looks false" is our reading of evidence text. A check could fail correctly for a reason that is not in its evidence line.
4. The 22 stale or edited copies of the declared command and the 16 "other prefix" calls were not read one by one.
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
