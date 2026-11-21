# Setup module

`/sql setup` writes the repo rules file (`docs/agents/sql.md`) and the user-local allowlist file, after one confirmation. Run the steps in this order. Never reorder them. Never skip a step, except Step 4 when its skip condition holds.

Every script needs Python 3.11 or newer. `<skill folder>` is the folder of this skill and `<repo root>` is the repo. Never read the PG password file (`PGPASSFILE`, `~/.pgpass`): setup reads service names only.

## Step 1: Detect

1. Read the rules file and the allowlist (a re-run has both):

   ```
   python3 <skill folder>/scripts/rules_file.py <repo root>
   python3 <skill folder>/scripts/allowlist.py <repo root>
   ```

   - The rules file `error` is set: stop. Show the parse error message and its line, and ask the developer to fix the file. Write nothing.
   - The allowlist `reason` is `malformed_file`: stop. Show its `detail` and write nothing.
   - Keep the result. It holds the current settings, the current `services`, and the `key` of the repo.
2. Scan the repo with no `--tags` and no `--receivers` option (this is tag and receiver detection only):

   ```
   python3 <skill folder>/scripts/setup_scan.py <repo root>
   ```

   It gives `files_with_sql`, `forms` (`template`, `sql` and `pg` counts), `detected_tags`, `detected_receivers`, `hints`, `candidates` and `truncated`. When `truncated` is true, tell the developer that only 1000 files were read. Tell the developer each text of `hints` once (a hint says that `pg` is a dependency and that no file shows a `pg` receiver, so the developer lists the receivers that the files import).

## Step 1b: Engine

This step sits after Step 1 and before Step 2, because it needs the rules file that Step 1 read. The existing step numbers do not change.

1. Run the engine detection on the repo (no `--file` option). Add `--request <engine>` only when the developer's request for setup names an engine (a lowercase word such as `mysql`):

   ```
   python3 <skill folder>/scripts/detect_engine.py <repo root> [--request <engine>]
   ```

   It gives `engine`, `signal`, `ask` and `evidence` (driver names, scheme names and file paths: it never prints a connection string).
2. Show the result in plain words: the engine, the signal that decided, and each `evidence` entry. On a re-run, also show the current `engine.name` and `engine.paths` of the settings that Step 1 read, as the current value (the detection without `--file` never reads `paths`).
3. Ask the developer to confirm or edit the engine. When `ask` is `clash` or `no_signal`, `engine` is null: ask the same question with no suggested engine, and show the evidence.
4. The repo shows two engines when the `evidence` list names two different engines. Only then, ask the developer for the `paths` entries: one `<folder>=<engine>` string for each folder that does not use the repo engine. The developer confirms or edits them.
5. Keep the confirmed engine for the proposal:
   - `engine.name` is the confirmed engine in lowercase. A PostgreSQL engine (the names `postgres` and `postgresql`) is written `postgres`.
   - `engine.paths` is the list of confirmed `paths` entries. Leave the key out when the list has no entry.
   - When the developer names no engine, the proposal carries no `engine`. Tell the developer that the engine stays unset. An unset engine keeps PostgreSQL, and Step 4 runs as today.

## Step 2: Tags and receivers

Show `detected_tags` and `detected_receivers`. Ask the developer to confirm or edit each list. The confirmed lists go into `[sources] tags` and `[sources] receivers`. A receiver entry is the receiver text as the call writes it, for example `pool` or `this.pool`.

- An empty confirmed list is allowed only when none was detected (tags for the tag list, receivers for the receiver list). When some were detected, the developer keeps at least one: ask again.
- Every later step uses the confirmed lists. When the developer changed a list, run the scan again with `--tags <confirmed tags>` and `--receivers <confirmed receivers>` (each option only when its list is not empty), so that the candidates and the file list follow them.
- An empty tag list means that no `--tags` option is passed to any command, and an empty receiver list means that no `--receivers` option is passed (the scripts reject an empty value).

## Step 3: Style and formatter

1. Measure the style on `files_with_sql` of the scan. Skip the measurer, and use the default style (`keyword_case` `upper`, `indent` `2 spaces`, `clause_per_line` true, `comma` `trailing`, `alias_as` true), when that list is empty:

   ```
   python3 <skill folder>/scripts/measure_style.py [--tags <confirmed tags>] [--receivers <confirmed receivers>] <file>...
   ```

   The `style` object of its output is the `[style]` proposal.
2. Detect the formatter. Run the detector once with `--form template` when `forms.template` is above 0, and once with `--form sql` when `forms.sql` is above 0. Pass `--tags <confirmed tags>` to the template run, and `--tool <name>` when the rules file has a `[formatter] tool`:

   ```
   python3 <skill folder>/scripts/detect_formatter.py <repo root> --form <template|sql> [--tags <t1,t2,...>] [--tool <name>]
   ```

3. Offer the install only when the main form has no safe tool. The main form is `template` when `forms.template` is above 0, else `sql` when `forms.sql` is above 0, and the detector of that form chose `none`. With no SQL at all, or a safe tool for the main form, make no offer and do not run the offer command.

   ```
   python3 <skill folder>/scripts/formatter_install.py offer <repo root> [--tags <confirmed tags>]
   ```

   - `offer` is false: say the `reason` in one line. No install.
   - `offer` is true: show `command`, `config.diff` and `package_json_diff` (show a null `package_json_diff` as "no change"). Ask the developer one question that only covers the install. This question is its own approval, and it comes before the final confirmation of Step 6. Approving the rules file never installs a package.
   - The developer approves: run `python3 <skill folder>/scripts/formatter_install.py apply <repo root> --confirm <digest> [--tags <confirmed tags>]`, then run the detector again. `ok` false: show its `reason` and `message`, and go on without a safe tool.
   - The developer declines: install nothing.
4. Choose the `[formatter] tool` value (one name): the template tool when the repo has templates and the detector chose one, else the `.sql` tool, else `none`.

## Step 4: Allowlist

Skip this step when the confirmed engine of Step 1b is not PostgreSQL and no `engine.paths` entry names PostgreSQL (`postgres` or `postgresql`). Setup then asks no service question, and the proposal has no `services`. This is the only step that setup skips. An unset engine does not skip it.

Otherwise, ask which PG service names the optimizer may use. Check the names that the developer types, against the PG service file (the `[name]` headers only):

```
python3 <skill folder>/scripts/setup_files.py services <name>...
```

Show each name in `service_check.missing`. The developer corrects it or keeps it (the warning stays in the plan). A re-run shows the current services and asks to keep them. An answer of "none" means no `services` key in the proposal (setup never removes an allowlist entry).

## Step 5: Interview

1. Show each candidate of the scan: its `text`, its `count` and its `evidence` (`file:line`). The developer keeps, edits or drops each one. The kept texts become prose rules.
2. Ask for rules of the developer's own. Each one is one line of text.
3. Setup never disables a rule. On a re-run keep the current `[rules] disabled` list in the proposal, and never change or drop a reason line.

## Step 6: Write

1. Write the proposal JSON with the Write tool into the system temp folder, never into the repo. Send every section, so that a re-run lists every differing key. Send `engine` only when Step 1b kept one, and send `services` only when Step 4 ran:

   ```
   {"settings": {"style": {...}, "formatter": {"tool": "..."}, "sources": {"tags": [...], "receivers": [...]}, "rules": {"disabled": [...]}, "engine": {"name": "...", "paths": ["<folder>=<engine>"]}}, "prose_rules": ["..."], "services": ["..."]}
   ```

2. Plan. This writes nothing:

   ```
   python3 <skill folder>/scripts/setup_files.py plan <repo root> --proposal <proposal file>
   ```

   - Run `plan` alone: never pipe or filter its output, because the whole JSON output must be in the result of the call (the digest of the confirmation comes from it).
   - A malformed file gives `ok` false: stop and show the message.
   - Resolve every `conflicts` entry first. Ask per key: keep the current value or take the proposed one. Drop a key that the developer keeps from the proposal, then run `plan` again. A re-run only appends prose rules: it never removes a hand-written line or comment.
3. Show the `warnings` and the `skipped_rules` (when there are any) in a message of your own. Then make the `write` call. A hook runs `plan` again for the same repo and proposal and shows the diff (`rules_file.diff`, and `allowlist.diff` when there is one) in the permission prompt. The prompt starts with a summary (one line per changed file, with its added and removed line counts) and a `Full diff: <path>` line, then the raw diff, which the prompt may fold; the file at that path holds the whole diff. So you do not print the diff. The `write` call is the question: Claude Code asks the developer to approve it in that permission prompt, and the permission prompt is the confirmation. Do not ask a separate question in text before the call. Use absolute paths for the repo folder and the proposal file in the `plan` and `write` commands, and call `write` alone as one command: the hook denies any other form. Do not put the script name followed by `write` in any other command (an `echo`, a `grep`, a commit message): the hook denies it too.
4. Call `write` with the digest of the latest plan. The developer sees the diff, then approves or declines it in the permission prompt:

   ```
   python3 <skill folder>/scripts/setup_files.py write <repo root> --proposal <proposal file> --confirm <digest>
   ```

   - The call is denied or declined (the permission prompt was refused, or no one could answer; a denial with a `Setup write check:` reason is the next case): stop for this turn. Do not write the files by any other route (the Write tool, a shell redirect, `tee`). Do not call `write` again in the same turn, with changed arguments or not. Say that nothing was written and ask the developer to confirm the diff. A later user message that confirms the diff allows one new `write` call with the digest of the latest plan.
   - The call is denied and the reason starts with `Setup write check:`: the hook could not check the call, so no prompt was shown and nobody was asked. This is not a decline. Fix the cause that the reason names (for example run `plan` again and use its new digest, use absolute paths, or call `write` alone) and call `write` again.
   - `reason` is `stale_digest`: a file changed after the diff. Run `plan` again and call `write` again with the new digest; the permission prompt shows the new diff.
   - `reason` is `write_failed` (nothing was written; this does not apply to a denied call): write the exact `text` of the latest `plan` output with the Write tool, for each file that has `changed` true (`rules_file.path` and `allowlist.path`). Change nothing else. This is the only direct edit of the two files. When the Write tool is denied for a file, stop for that file: show its path and its `text` to the developer in the final message, and say that it was not written.
5. A stopped setup leaves the rules file and the allowlist unwritten. The formatter install of Step 3 has its own earlier approval.

## Step 7: Report

Name, from the outputs above:

- `Formatter: <the chosen tool or none>`. With no SQL in the repo no detector ran: say so.
- `Other tools found: <the tools of found that are not chosen, or none>` (from the detector output).
- The tags, the receivers, the services, and what was written (the file paths, or "nothing written").
- Each warning once.
