# postgres.js templates source module

Load this module when the SQL is in a postgres.js tagged template of a JavaScript or TypeScript file (the router's source module rule). It tells you how to find each template, its tag and its interpolations.

## Find the templates

1. Get the tag list. Take it from `tags` of the `[sources]` section of the rules file (the router's rules file step). With no `[sources]` section, or an empty `tags` list, run with no `--tags`: the script then uses the tags that the file shows, for that run only (the router's rules file step names the fallback once).
2. Run the extractor. Pass the tag list with `--tags`, as one comma-separated value. A tag can be a member form such as `this.sql`.

```
python3 <skill folder>/scripts/extract.py <file> --tags sql,this.sql,tx
```

It prints one JSON object with the keys `file`, `form` (`js`), `detected_tags`, `factory_names`, `tags`, `statements` and `error`.

- `detected_tags`: the tags that the file shows. It finds them in these forms: a variable that holds `postgres(...)`, a member form such as `this.sql = postgres(...)`, a class field, and the first parameter of a `.begin(tx => ...)` callback. Tell the user about a detected tag that is not in the repo tag list, because the repo list may miss it.
- `factory_names`: the local names that the file binds to the postgres.js package (`import postgres from 'postgres'`, `require('postgres')`).
- `tags`: the tag list that the run matched. It is the `--tags` list, or `detected_tags` when you gave none.
- A tag that the file imports from another module (`import { sql } from './db'`) cannot be detected. The repo tag list must name it.

Each item of `statements` is one template:

- `tag`: the tag text (`sql`, `this.sql`, `tx`).
- `start_line` and `end_line`: the lines of its opening and closing backtick.
- `text`: the exact text between the backticks. The `${...}` text stays in it.
- `parent`: the index in `statements` of the template that holds this one in a `${...}`, or null. A conditional fragment (``${cond ? sql`AND a = 1` : sql``}``) is its own statement with a `parent`.
- `interpolations`: only the `${...}` of this template's own body. Each has `line`, `column`, `expression` and `position`.

Name each template to the user as `<file>:<start_line>-<end_line> <tag>`.

## Read `position`

- `value`: the interpolation stands for a value or an expression (`WHERE id = ${id}`, `ORDER BY ${sql(col)}`).
- `fragment`: the interpolation stands for a whole clause or a conditional part (`WHERE a = 1 ${active ? sql`AND active` : sql``} ORDER BY id`).
- `keyword`: the interpolation sits where the SQL grammar is not clear (`${sel} * FROM users`, `FROM t ${dir} BY id`). The format mode uses the written style for a template with a `keyword` interpolation (spec story 45).

The `value` and `fragment` positions are only reported. The format tickets decide what to do with them.

## Errors

If `error` is not null, stop. Show its `message` and its `line` (the line can be null when the file cannot be read), and ask the user to fix the file. The script exits with code 1 in this case, and with code 2 for a usage error (it prints no JSON then).

## Rules

This module holds no `PGJS-*` rule yet. A later ticket adds them under a heading that it names.
