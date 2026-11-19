# Setup module

`/testing setup` writes the repo rules file (`docs/agents/testing.md` in the product repo). Run the steps in this order. Never skip a step and never reorder them. A step that has nothing to do keeps its heading and does nothing.

`<skill folder>` is the folder of this skill. `<repo root>` is the git top-level folder of the current folder, else the current folder. The intake script needs Python 3.11 or newer.

Setup does not run any test and does not edit any file except the rules file. A re-run edits the file with Edit calls and never rewrites it.

## Step 1: Detect

Run the intake script with the repo root only (no file argument):

```
python3 <skill folder>/scripts/intake.py <repo root>
```

- Exit code 2: report the message and stop.
- Exit code 1 with no JSON on stdout: the command failed. Report the output and stop.
- Exit code 1 with the JSON (`rules.error` is set): show the message and its line (leave out the line when it is null), write nothing and stop.

Keep these keys of the output: `rules.found`, `rules.settings`, `rules.missing_sections`, `rules.unknown_ids`, `rules.disabled_without_reason`, `detected.languages` and `detected.facts`.

`rules.found` false means a **new file**. `rules.found` true means a **re-run**.

**Re-run guard.** A re-run edits the file only when it holds a closed `toml` block and `rules.missing_sections` has no entry except `commands.<language>` entries. Otherwise show the entries (or say that the file has no `toml` block), write nothing and stop. The user repairs the file by hand, or moves it away and runs setup again.

## Step 2: Interview

Ask four questions, always in this order. Each question can be skipped. A skipped question changes nothing. On a re-run, show the recorded value first. A recorded group or a recorded disabled id is shown and cannot be edited here. A skip keeps the recorded value.

1. **Groups.** Skip this question when no language is available (a new file with no detected language), because no group could name a valid language. For each group ask for `name`, `language`, `size` (`small`, `medium` or `large`) and `command`. The `language` is a language of the recorded `[[languages]]` on a re-run, and a detected language on a new file.
2. **Limits.** Ask for `small_ms` and `medium_ms` (positive integers, `medium_ms` not below `small_ms`). An answer for only one limit is compared with the recorded value of the other limit, else with the default of that limit: 100 and 1000.
3. **Rule ids to disable.** Offer the ids of the `## Catalogue` table of [general.md](general.md). Ask for a reason for each id. An id that is typed without a reason is asked once for its reason. With no reason it is not disabled, but it still goes through step 3.
4. **Conventions.** Ask for conventions of the team, one line of prose each.

Reject an answer, and ask the question again, when it breaks one of these rules: a limit that is not a positive integer; `medium_ms` below `small_ms`; a group `language` that is not a valid language (see question 1); a `size` that is not one of the three; an empty `command`; a group name that is already used; a reason or a convention that is not one non-empty line or that starts with a code fence.

## Step 3: Unknown ids

When no id was named, this step does nothing.

Otherwise run the intake script on a temporary root, for every named id, with or without a reason. The root is a new folder under the system temp directory. Its name ends with a random 8-character suffix, so that parallel runs do not collide. Make its `docs/agents/testing.md` with the Write tool. Remove nothing. The file holds only this block:

````
```toml
[rules]
disabled = ["<the named ids>"]
```
````

- An id that holds a character other than a letter, a digit or a hyphen is shown as unknown without the run.
- Each id in `rules.unknown_ids` of the output is shown as unknown and is not written.
- Each other id without a reason is reported as "no reason, not disabled".
- The other ids go on.

## Step 4: Draft

A **new file** is drafted whole (see "File layout").

A **re-run** builds a numbered table with the columns `# | Key | Recorded | Detected`. A row is one key of the sections `commands`, `runner`, `layout` or `libraries`. The key is written `<section>.<language>.<key>`, for example `runner.typescript.package_manager`. A row exists for a language that the recorded `[[languages]]` lists, in these cases:

- The recorded value differs (JSON equality) from a detected value whose status is `detected`.
- The recorded file lacks the key, and detection has a value whose status is `detected` or `default`.

The row order is fixed: the sections in the order `commands`, `runner`, `layout`, `libraries`, then the languages in the order of `detected.languages`, then the keys in the order of `detected.facts`.

- A detected value with status `default` never replaces a recorded value.
- A key whose detected value is null or whose status is `unknown` is never proposed.
- A value that equals the recorded one is not shown.
- The keys of `groups`, `limits` and `rules`, and the prose, are interview keys. They get no row.

A key that setup cannot edit safely has no row. List it in the report as **not handled**. These are the not-handled keys:

- A key of a table that has no `[name]` header line of its own in the file (a table written inline or with dotted keys, `limits` and `rules` included, so an answer for them is not handled either).
- A table or section that the file lacks (except `[limits]` and `[rules]`, see rule (c) of step 5).
- A non-empty `groups` array written inline (with no `[[groups]]` header).
- A detected language that `[[languages]]` does not list.

A not-handled answer is not written, its prose lines included, and counts as no answer.

**Re-run answer states.** Each interview answer and each row is in exactly one state:

- **written**: valid, handled and approved;
- **dropped**: invalid, declined by the reply, an unknown id, an id with no reason, or an id already recorded with its reason line;
- **not handled**: listed in the report and never written.

Only written items change the file. When no item is written (no answer and no row), show "nothing to change", write nothing, skip Step 6 and go to Step 7.

## Step 5: Approve and write

Show the new file, or the answers and the table, and ask for approval. Write nothing to the rules file before the approval.

- New file: the reply is `yes` or `no`.
- Re-run with rows: use the reply grammar of step 2 of "Fix on approval" in [review.md](review.md) (`all`, `none`, a list or a range of row numbers). The reply `answers` writes the answers and no row. It cannot be combined with row numbers, and `all` includes the answers. The interview answers are all or nothing: `none` writes nothing, and any other reply writes every answer that was not dropped, with the chosen rows.
- Re-run with answers and no row: the reply is `yes` or `no`.
- An invalid reply edits nothing, names the invalid part and waits.
- A reply that writes nothing (`no`; for a re-run with rows also `none`) skips Step 6 and goes to Step 7, which reports "declined".

A new file is written with the Write tool. A re-run edits the existing file with Edit calls. One Edit changes or adds one key, one table or one line. The placement rules are:

- (a) A recorded key is changed on its own line. A multi-line array is edited as a whole.
- (b) A missing key of an existing table is added on the line after the header of that table.
- (c) A `[limits]` or `[rules]` table that the file holds in no form (no header, no inline table, no dotted key) is added at the end of the `toml` block, before the closing fence. It holds every answered key, in one Edit.
- (d) A new group is added as a `[[groups]]` table at the end of the block. A bare `groups = []` line, when present, is removed with its own Edit.
- (e) A disabled id is added to the `disabled` array of `[rules]` by rule (a), (b) or (c). It also gets its line `- <ID>: <reason>` under `## Disabled rules`. Each is skipped when it is already present. A convention gets its line `- <text>` under `## Conventions`. Add a heading at the end of the file when it is absent.

A re-run cannot edit or remove a recorded group or a recorded disabled id. The user edits those by hand. A group name that is already recorded is rejected, as in step 2.

## Step 6: Check

Run the intake script on the repo root again.

- New file: exit code 0, `rules.found` true, no `unknown_ids`, no `disabled_without_reason`, and `missing_sections` empty. The one **expected gap** is allowed: a `commands.<language>` entry for a language whose test command detection could not find. It is reported, not fixed.
- Re-run: exit code 0, no entry in `unknown_ids` or `disabled_without_reason` that the Step 1 output did not have, and no `missing_sections` entry beyond those of Step 1.

On a failure, fix the file with Edit and check again, at most 2 times. Then report the failure.

## Step 7: Report

State what was written: the path, and "new file", or the number of changed values (the approved rows plus the written answers; an answer is one group, one limit, one disabled id or one convention), or "declined", or "nothing to change". Also state:

- each key that was skipped;
- each key that is not handled;
- each unknown id;
- each fact that detection could not find (name the language of the expected gap once);
- when no language was detected, that no language was detected.

## File layout

A new file always holds the six required sections: `languages`, `commands`, `groups`, `runner`, `layout` and `libraries`. So a skipped question can leave only a key unset, never a required section missing.

The file holds, in this order:

1. The title line `# Test rules`.
2. One fenced `toml` block.
3. The prose section `## Disabled rules` with the lines `- <ID>: <reason>`, only when it has a line.
4. The prose section `## Conventions` with one `- ` line each, only when it has a line.

The block order is `[[languages]]` (the name and root of each detected language), `commands`, `groups`, `runner`, `layout`, `libraries`, then `limits` and `rules` only when answered.

- An empty array of tables (`languages` or `groups` with no entry) is the bare line `languages = []` or `groups = []` at the very top of the block, before any table header. A bare key after a header belongs to that table.
- Each group is a `[[groups]]` table with the keys `name`, `language`, `size` and `command`.
- A skipped limits question writes no `[limits]`. A skipped disabled question writes no `[rules]`. A skipped groups question writes `groups = []`.
- Each per-language table (`[commands.<language>]`, `[runner.<language>]`, `[layout.<language>]`, `[libraries.<language>]`) holds every detected fact of its section whose value is not null and whose status is `detected` or `default`. A per-language table is always written, even when it has no key.
- A list is a TOML array. A table is an inline table. A string is written with TOML escapes for `"` and `\`. A key that is not a bare TOML key is quoted.
- A repo with no Rust or TypeScript manifest gets the six sections with `languages = []`, `groups = []` and empty tables. The report says that no language was detected.
