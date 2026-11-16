---
type: llm
---
Grader of the refused pg rewrite (replaces the style check, because the statement is left as it was).

The fixture `audit-store.ts` has 12 lines. The chain on lines 7 to 9 has a comment between its two pieces:

```
    'select id, name from users ' +
      // active users only
      'where active order by name',
```

Look at the file that the final message of Claude shows (the file after the first run). Pass when the whole file is exactly as the fixture was: the chain still has its two quoted pieces, the `+` and the comment line, in the same order, with the same text and the same indent, and no template was made. Fail when any character of the file changed.
