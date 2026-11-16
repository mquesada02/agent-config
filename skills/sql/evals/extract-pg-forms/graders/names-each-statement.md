---
type: llm
---
The final answer of Claude must list exactly these seventeen statements of `order-reports.ts`, each with its line range and its form (a statement on one line has a range such as `19-19`):

| Lines | Form |
|---|---|
| 8-8 | `literal` |
| 10-11 | `chain` |
| 19-19 | `literal` |
| 20-20 | `template` |
| 21-21 | `literal` |
| 22-22 | `literal` |
| 23-23 | `literal` |
| 24-24 | `literal` |
| 27-27 | `chain` |
| 28-28 | `chain`, `dynamic` |
| 29-29 | `template`, `dynamic` |
| 33-33 | `literal` |
| 39-39 | `literal` |
| 40-40 | `literal` |
| 42-42 | `literal` |
| 50-50 | `literal` |
| 51-51 | `literal` |

The answer must also list exactly these five `query()` calls as not followed, each by its line: 30, 31, 32, 44 and 45.

Pass when the answer names all seventeen statements with the right line ranges and forms, marks the two dynamic ones, and lists the five not-followed lines. Fail when it misses a statement, gives a wrong line range or form, leaves out `dynamic` on line 28 or 29, adds a statement for a line that is not in the table, or lists one of the five lines as a statement or leaves one out of the not-followed list. The answer may add other words, but the lists must be in the answer.
