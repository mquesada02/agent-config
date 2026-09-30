#!/usr/bin/env bash
# Keep skills model-invocable: flip `disable-model-invocation: true` to false
# in plugin and claude.ai-synced skill frontmatter. Plugin updates and re-syncs
# overwrite these files, so this runs at every fresh session start; a file reset
# mid-session is fixed from the next session on.
# i-have-adhd is excluded: its own hook already loads it every session.
# Workaround: skillOverrides has no "force on" value, so the hook edits Claude
# Code's internal plugin-cache and synced-skill folders, which any release can
# change. Replace it if Claude Code adds a setting to allow model invocation.
exec 2>/dev/null  # a session-start hook must stay silent
flag='^disable-model-invocation:[[:space:]]+true([[:space:]]+#.*|[[:space:]]*)$'
grep -rlZE "$flag" --include=SKILL.md --exclude-dir=i-have-adhd \
  "$HOME/.claude/plugins/cache" "$HOME/.claude/skills/synced" |
while IFS= read -r -d '' f; do
  [ -w "$f" ] || continue
  # Same-directory temp file + mv: parallel sessions never see a half-written file.
  tmp=$(mktemp "${f%/*}/.SKILL.md.XXXXXX") || continue
  awk -v flag="$flag" '
    NR == 1 && $0 == "---" { fm = 1; print; next }
    fm && $0 == "---"      { fm = 0 }
    fm && $0 ~ flag        { sub(/true/, "false") }
    { print }' "$f" > "$tmp" &&
    ! cmp -s "$tmp" "$f" &&
    chmod --reference="$f" "$tmp" &&
    mv "$tmp" "$f"
  rm -f "$tmp"
done
exit 0
