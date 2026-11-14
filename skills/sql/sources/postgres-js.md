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

## Regex or division

In every JavaScript and TypeScript file the extractor decides from the last tokens whether a `/` starts a regex or is a division. Two rules apply before the usual rule (a regex starts after an operator, an opening bracket or a regex keyword such as `return`):

- After a postfix `++` or `--`, the `/` is a division: `i++ / 2`. Two separate operators, as in `a + +/re/.source`, are not a postfix operator, so the `/` there starts a regex.
- Right after the words `export default`, the `/` starts a regex: `export default /re/`. The name `default` in any other place is a value, so `obj.default / 2` is a division.

## JSX scan

In `.jsx` and `.tsx` files the extractor scans each JSX element as one unit, from its opening `<` to its matching close. JSX text and attribute strings never open a JavaScript string, template, regex or comment, so an apostrophe, a double quote or a backtick in JSX text does not hide a later template. A `{...}` child or attribute value is JavaScript again, so a template inside it is found. Other extensions do not change.

- An element starts at a `<` where an expression can start (not after a name, number, string, `)`, `]`, `}`, a postfix `++` or `--`, or the end of a template), when a name or `>` (a fragment) follows. A regex keyword such as `return` and the words `export default` (`export default <p/>`) before the `<` do not count as values.
- In `.tsx`, a generic arrow function is TypeScript, not JSX (the rule of the TypeScript parser for `.tsx`): after `<`, an optional `const` and a name, a `,`, an `=` that is not `=>`, or `extends` followed by something other than `=`, `>` or `/`. Examples: `<T,>(x: T) => x`, `<T extends U>(x: T) => x`. Type arguments in a call (`f<T>(x)`) are TypeScript too.
- An element that is still open at the end of the file gives the error `unterminated JSX element` with the line of the innermost element that is still open.
- Tag names are not compared, so a mismatched close such as `<a></b>` is accepted and closes `a`.
- Known limits, not handled and not tested (the result for these inputs is not defined): an element used as an attribute value (`attr=<b/>`), type arguments on a component (`<Foo<string> x={1} />`), a comment inside a tag (`<a /* c */ b/>`), and a generic function type in a type position in `.tsx` (`x: <T>(a: T) => T`).

## Rules

These rules check how a postgres.js template is composed. They work with no database (PGJS-02 can also read a column type from the catalog when the database is allowlisted). A fix of a `PGJS-*` finding repairs the template. It is not a rewrite of the SQL text.

### PGJS-01

- **Title:** Wrong `IN` list
- **Severity:** critical
- **Detects:** `IN (${sql(array)})` (extra parentheses around the helper) or `IN ${array}` (a plain array and no `sql()` helper). The correct form `IN ${sql(array)}` is not a finding.
- **Why it matters:** The extra parentheses make the driver write `IN ((1, 2))`, which compares the column with one row value. A plain array is sent as one array parameter, so the list is not expanded and the query fails or matches nothing.
- **Fix:** Write `IN ${sql(array)}`. Put no parentheses around the helper.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  sql`SELECT * FROM users WHERE id IN (${sql(ids)})`
  ```

  Good:

  ```js
  sql`SELECT id FROM users WHERE id IN ${sql(ids)}`
  ```

### PGJS-02

- **Title:** JS `Date` passed to a `date` parameter
- **Severity:** required
- **Detects:** A JS `Date` value bound to a parameter that is a `date`. With an allowlisted database, the `date` fact comes from the catalog: the `facts` action says that the column has the type `date` (the `Date` value fact still comes from the repo). Without a database this fires only when the repo shows both facts: a `Date` value (a TypeScript type, `new Date(...)` or a `Date` variable) and a `date` parameter (a `::date` cast in the SQL, or a migration or schema column of type `date`). Otherwise the rule does not fire.
- **Why it matters:** The driver sends a `Date` as a UTC timestamp (`toISOString()`, typed `timestamptz`). When that instant is cast to `date`, the day is the day of the session time zone. It can differ from the local calendar day of the caller, so the day can shift.
- **Fix:** Pass the day as text (`'2026-11-09'`), or format the `Date` to its day before the call.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  sql`SELECT id FROM invoices WHERE due_on = ${new Date()}::date`
  ```

  Good:

  ```js
  sql`SELECT id FROM invoices WHERE due_on = ${isoDay}::date`
  ```

### PGJS-03

- **Title:** Empty fragment leaves a dangling keyword
- **Severity:** critical
- **Detects:** A conditional fragment whose empty branch leaves a dangling `AND`, `OR` or `WHERE` in the final SQL.
- **Why it matters:** When the condition is false, the SQL has a keyword with no condition after it, or a `WHERE` with nothing. The query then fails with a syntax error.
- **Fix:** Keep `WHERE` outside the fragment with a condition that always exists, and put `AND` or `OR` inside the fragment, in front of its condition. Then an empty fragment leaves valid SQL.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  sql`SELECT id FROM users ${role ? sql`WHERE role = ${role}` : sql``} AND active = true`
  ```

  Good:

  ```js
  sql`SELECT id FROM users WHERE active = true ${role ? sql`AND role = ${role}` : sql``}`
  ```

### PGJS-04

- **Title:** `sql.unsafe` with a value that is not a constant
- **Severity:** critical
- **Detects:** `sql.unsafe(...)` with an argument that is not a string constant: a variable, a template literal with `${...}`, or a concatenation.
- **Why it matters:** `sql.unsafe` puts its text into the SQL with no parameter. A value from a user in that text is an SQL injection.
- **Fix:** Use a parameter (`${value}`). For an identifier, use the `sql(name)` helper.
- **Example:** The bad form, then the good form.

  Bad:

  ```js
  sql.unsafe(`SELECT id FROM users WHERE name = '${name}'`)
  ```

  Good:

  ```js
  sql`SELECT id FROM users WHERE name = ${name}`
  ```
