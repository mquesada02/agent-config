---
type: llm
arm: with-only
---
Judge the finding rows of the report one row at a time. A row passes when its Fix cell names a concrete edit (what to add, change, remove or rename, with the key or value when the edit needs one) that answers the problem in its Problem cell. You see the report, not the workflow files: judge by the two cells, and do not fail a row because you cannot see a file.
A row marked with ⚑ passes when its Fix cell names the workflow edit and the admin steps for branch protection are in the ⚑ section (the skill does not change branch protection itself). PASS if every row passes. FAIL if a Fix cell is vague, such as "improve the name", or does not answer its Problem cell.
