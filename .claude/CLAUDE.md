## Agent skills

### Issue tracker

Issues live in GitHub Issues on `mquesada02/agent-config`. See `~/.claude/docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `~/.claude/docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root (`~/.claude`). See `~/.claude/docs/agents/domain.md`.

### Test command

Run this command from the repo root to run every test file of the hook and skill folders in one process.

```
python3 -c "import sys, unittest; suite = unittest.TestSuite(); [suite.addTests(unittest.defaultTestLoader.discover(d, top_level_dir=d)) for d in ('hooks/context-handoff', 'hooks/workflow-audit', 'skills/plan-review')]; sys.exit(not unittest.TextTestRunner().run(suite).wasSuccessful())"
```
