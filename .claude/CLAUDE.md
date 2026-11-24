## Agent skills

### Issue tracker

Issues live in GitHub Issues on `mquesada02/agent-config`. See `~/.claude/docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `~/.claude/docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root (`~/.claude`). See `~/.claude/docs/agents/domain.md`.

### Test command

Run this command from the repo root to run every test file of the hook and skill folders in 2 processes at the same time (the folder list is in `scripts/run-tests.py`).

```
python3 scripts/run-tests.py
```

The full run can take longer than the 600 s foreground limit. Start this exact command with `run_in_background: true`, and wait for its completion notification.
