# `.sql` files source module

Load this module when the SQL is in a file that ends in `.sql` (the router's source module rule). It tells you how to find the statements of the file. The `PG-*` rules are in the dialect module.

## Find the statements

Run the extractor with no `--tags`. The script accepts `--tags` for a `.sql` file and ignores it.

```
python3 <skill folder>/scripts/extract.py <file>
```

It prints one JSON object. The keys are `file`, `form` (`sql`), `detected_tags`, `factory_names`, `tags`, `statements` and `error`. For a `.sql` file `detected_tags`, `factory_names` and `tags` are always empty.

Each item of `statements` is one statement of the file:

- `start_line` and `end_line`: the lines of its first and last character. The `;` that ends it is not part of it.
- `text`: the exact source text of the statement.
- `tag` and `parent`: always null for a `.sql` file.
- `interpolations`: the `${...}` placeholders inside the statement. Each has `line`, `column`, `expression` and `position`.

A comment before the first token or after the last token of a statement is not part of it. Text that holds only white space and comments is not a statement.

## Read `position`

A `.sql` file may hold `${...}` placeholders. Each one has a `position`:

- `value`: the placeholder stands for a value or an expression (`WHERE id = ${id}`).
- `fragment`: the placeholder stands for a whole clause or a conditional part (`WHERE a = 1 ${filter} ORDER BY id`).
- `keyword`: the placeholder sits where the SQL grammar is not clear (`${columns} FROM users`). The format mode uses the written style for a statement with a `keyword` placeholder (spec story 45).

The `value` and `fragment` positions are only reported. The format tickets decide what to do with them.

## Errors

If `error` is not null, stop. Show its `message` and its `line` (the line can be null when the file cannot be read), and ask the user to fix the file. The script exits with code 1 in this case, and with code 2 for a usage error (it prints no JSON then).

## Rules

This module holds no rule yet. A later ticket adds rules for `.sql` files under a heading that it names.
