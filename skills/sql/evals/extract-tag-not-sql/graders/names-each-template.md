---
type: llm
---
The final answer of Claude must list exactly these four postgres.js templates of `billing-store.ts`, each with its line range and its tag:

| Lines | Tag |
|---|---|
| 9-13 | `db` |
| 24-26 | `this.db` |
| 32-32 (line 32 only) | `tx` |
| 33-33 (line 33 only) | `tx` |

Pass when the answer names all four, each with the right line range and the right tag. Fail when it misses one, gives a wrong line range or a wrong tag, or lists a template under the tag `sql`: the text `sql` in the comment on line 5 and in the string on line 6 is not a template, so no entry for them may appear. The answer may add other words, but the list must be in the answer.
