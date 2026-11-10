---
type: llm
---
Grader A of seam 2 (the same check as the command `graders/interpolations_same.py`).

The target template of `notes-store.ts` (`listNotes`, line 5) has one interpolation, `${owner}` (a value), in the `where` clause. Look at the file that the final message of Claude shows (the file after the first run). The original line of the target is `export const listNotes = (owner: number) => sql`select id, body from notes where owner_id = ${owner} order by id``. Compare it with the file that the final message shows. Pass when the template still holds `${owner}` once, with the same text, after the `where` clause word and before the `order by` clause word. Fail when it is changed, dropped or moved.
