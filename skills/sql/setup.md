# Setup module

`/sql setup` writes the repo rules file (`docs/agents/sql.md`) and the user-local allowlist file, after one confirmation. Run the steps in this order. Never skip a step and never reorder them. Before the `write` call of Step 6, you must have sent one message of your own that starts with `Diff to confirm:` and holds the diff. A `write` call without that message is an error, even when nobody can answer.

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
2. Scan the repo with no `--tags` option (this is tag detection only):

   ```
   python3 <skill folder>/scripts/setup_scan.py <repo root>
   ```

   It gives `files_with_sql`, `forms` (`template` and `sql` counts), `detected_tags`, `candidates` and `truncated`. When `truncated` is true, tell the developer that only 1000 files were read.

## Step 2: Tags

Show `detected_tags`. Ask the developer to confirm the list or to edit it. The confirmed list goes into `[sources] tags`.

- An empty confirmed list is allowed only when no tag was detected. When tags were detected, the developer keeps at least one: ask again.
- Every later step uses the confirmed list. When the developer changed it, run the scan again with `--tags <confirmed tags>`, so that the candidates and the file list follow it.
- An empty tag list means that no `--tags` option is passed to any command (the scripts reject an empty value).

## Step 3: Style and formatter

1. Measure the style on `files_with_sql` of the scan. Skip the measurer, and use the default style (`keyword_case` `upper`, `indent` `2 spaces`, `clause_per_line` true, `comma` `trailing`, `alias_as` true), when that list is empty:

   ```
   python3 <skill folder>/scripts/measure_style.py [--tags <confirmed tags>] <file>...
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

Ask which PG service names the optimizer may use. Check the names that the developer types, against the PG service file (the `[name]` headers only):

```
python3 <skill folder>/scripts/setup_files.py services <name>...
```

Show each name in `service_check.missing`. The developer corrects it or keeps it (the warning stays in the plan). A re-run shows the current services and asks to keep them. An answer of "none" means no `services` key in the proposal (setup never removes an allowlist entry).

## Step 5: Interview

1. Show each candidate of the scan: its `text`, its `count` and its `evidence` (`file:line`). The developer keeps, edits or drops each one. The kept texts become prose rules.
2. Ask for rules of the developer's own. Each one is one line of text.
3. Setup never disables a rule. On a re-run keep the current `[rules] disabled` list in the proposal, and never change or drop a reason line.

## Step 6: Write

1. Write the proposal JSON with the Write tool into the system temp folder, never into the repo. Send every section, so that a re-run lists every differing key:

   ```
   {"settings": {"style": {...}, "formatter": {"tool": "..."}, "sources": {"tags": [...]}, "rules": {"disabled": [...]}}, "prose_rules": ["..."], "services": ["..."]}
   ```

2. Plan. This writes nothing:

   ```
   python3 <skill folder>/scripts/setup_files.py plan <repo root> --proposal <proposal file>
   ```

   - Run `plan` alone: never pipe or filter its output, because the whole JSON output must be in the result of the call (the digest of the confirmation comes from it).
   - A malformed file gives `ok` false: stop and show the message.
   - Resolve every `conflicts` entry first. Ask per key: keep the current value or take the proposed one. Drop a key that the developer keeps from the proposal, then run `plan` again. A re-run only appends prose rules: it never removes a hand-written line or comment.
3. Show the one diff. Print `rules_file.diff` and `allowlist.diff` (an absent `allowlist` means no allowlist change) as text in a message of your own, in a code block, together with the `warnings` and the `skipped_rules`. Do this before any write, even when the developer gave the confirmation in advance. The diff text must be in your own message: the result of a tool call does not count. Start that message with the line `Diff to confirm:`, then give the diff in a code block. Make the `write` call only after that message. The `write` call is the question: Claude Code asks the developer to approve it in a permission prompt, and that permission prompt is the confirmation. Do not ask a separate question in text before the call.
4. Call `write` with the digest of the latest plan. The developer approves or declines it in the permission prompt:

   ```
   python3 <skill folder>/scripts/setup_files.py write <repo root> --proposal <proposal file> --confirm <digest>
   ```

   - The call is denied or declined (the permission prompt was refused, or no one could answer): stop for this turn. Do not write the files by any other route (the Write tool, a shell redirect, `tee`). Do not call `write` again in the same turn, with changed arguments or not. Say that nothing was written and ask the developer to confirm the diff. A later user message that confirms the diff allows one new `write` call with the digest of the latest plan.
   - `reason` is `stale_digest`: a file changed after the diff. Run `plan` again, show the new diff and call `write` again.
   - `reason` is `write_failed` (nothing was written; this does not apply to a denied call): write the exact `text` of the latest `plan` output with the Write tool, for each file that has `changed` true (`rules_file.path` and `allowlist.path`). Change nothing else. This is the only direct edit of the two files. When the Write tool is denied for a file, stop for that file: show its path and its `text` to the developer in the final message, and say that it was not written.
5. A stopped setup leaves the rules file and the allowlist unwritten. The formatter install of Step 3 has its own earlier approval.

## Step 7: Report

Name, from the outputs above:

- `Formatter: <the chosen tool or none>`. With no SQL in the repo no detector ran: say so.
- `Other tools found: <the tools of found that are not chosen, or none>` (from the detector output).
- The tags, the services, and what was written (the file paths, or "nothing written").
- Each warning once.
