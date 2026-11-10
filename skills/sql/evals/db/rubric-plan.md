You score the explanation and the fix text of a `/sql optimize` report. The report comes from a skill that reads a real query plan. Its `PLAN-*` rows state a measured value against a threshold, then explain the cause, then give a fix.

Score only the rows whose Rule cell starts with `PLAN-`. Give one whole number from 0 to 5.

- 5: every PLAN row names the plan node and the measured value, explains the real cause in plain words, and gives a fix that fits the cause (for example an index on the filtered column, or a smaller select list). The fix is advice in words, with no replacement SQL.
- 3: the cause or the fix is correct but generic, or one row misses its measured value.
- 1: the explanation repeats the numbers and gives no cause, or the fix does not fit the cause.
- 0: there is no PLAN row, or the explanation is wrong.

A report that holds no PLAN row and has nothing to approve for this reason (the plan is clean) scores 5 when it states no false problem.

Answer with exactly one line and nothing else, in this form: `SCORE: <n>/5 <one short reason>`.
