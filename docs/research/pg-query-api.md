# pg (node-postgres) query API: which forms of SQL text it accepts

## Summary

Version read: `pg@8.23.1` (npm `latest`; git tag `pg@8.23.1`, commit `0980cefebe0ae461da8883703be049fe13ca96cf`). The source was read from that tag.
`query()` takes a string, a string plus a values array, a config object, or a submittable (an object with a `submit` function).
`pg` never rewrites the SQL text. It sends the string as given.
The path depends on the Query fields: no `values` (or an empty array), no `name`, no `rows`, and no `queryMode: 'extended'` means the simple protocol (several statements allowed). A non-empty `values` array, a `name`, `rows`, or `queryMode: 'extended'` means the extended protocol (PostgreSQL rejects more than one statement).
`query()` exists on `Client`, `Pool`, a pool client, and `pg.native` clients. `pool.query` delegates to `client.query`.
The ESM build (`import { Pool } from 'pg'`) has named exports since `pg@8.15.0`.

Link base used below: `https://github.com/brianc/node-postgres/blob/pg@8.23.1/` (written as `GH/`).

## 1. `client.query(text)`, `(text, values)`, `(config)`

Entry point: `Client.query(config, values, callback)` in [GH/packages/pg/lib/client.js#L668-L785](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L668-L785). A `null` or `undefined` first argument throws a `TypeError` (L673-L675).

Normalization is in `normalizeQueryConfig` ([packages/pg/lib/utils.js#L154-L169](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/utils.js#L154-L169)):
- A string becomes `{ text: string }`. A config object is cloned.
- If the second argument is truthy and not a function, it becomes `config.values`. If it is a function, it becomes `config.callback`.
- A third argument becomes `config.callback`.

The docs list the same shapes: text only, parameterized, and config object ([docs/pages/features/queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), sections "Text only", "Parameterized query", "Query config object"; [docs/pages/apis/client.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/client.mdx), section "client.query"). The website copy is https://node-postgres.com/features/queries and https://node-postgres.com/apis/client.

Fields that the `Query` constructor reads ([packages/pg/lib/query.js#L9-L33](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L9-L33)):

| Field | Effect | Source |
|---|---|---|
| `text` | The SQL string. Sent as is. | query.js L14 |
| `values` | Bind parameters. Must be an array, else `Query values must be an array`. | query.js L160-L162 |
| `name` | Prepared statement name. Forces the extended protocol. | query.js L41-L43 |
| `rowMode` | `'array'` returns rows as arrays. Does not change how text is sent. | query.js L24; docs "Row mode" |
| `types` | Custom type parsers for the result. Also passed to `parse` as `types` (parameter type OIDs). | query.js L17, L216-L220; docs "Types" |
| `queryMode` | `'extended'` forces the extended protocol. | query.js L36-L38 |
| `rows` | Max rows per portal execution. Forces the extended protocol. Not in the docs. | query.js L46-L48 |
| `binary` | Result format in `bind`. The client also sets it from the `binary` option. | query.js L20, L230-L235; client.js L739-L741 |
| `portal` | Portal name. | query.js L22 |
| `callback` | Callback form. | query.js L23 |
| `query_timeout` | Read timeout. Read from the config in `Client.query`. | client.js L702 |

The docs mark `queryMode` as "TODO: document" ([client.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/client.mdx), the `QueryConfig` type block). The `queryMode` value `'extended'` is confirmed only from source. Any other value is not confirmed to do anything.

A query needs a string `text` or a string `name`, else `submit` returns `A query must have either text or a name. Supplying neither is unsupported.` ([query.js#L152-L155](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L152-L155)). So a name-only query (re-run of a prepared statement) is accepted.

A named statement used again with different text fails: `Prepared statements must be unique` (query.js L156-L159).

The docs say `pg` passes the text "_unaltered_" ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), "Parameterized query").

## 2. `Query` objects and other submittables

`Client.query` checks `typeof config.submit === 'function'`. If true, the object itself is queued and returned. No `Query` is built ([client.js#L677-L685](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L677-L685)). A callback passed as the second or third argument is set on it if it has none.

The docs: "If you pass an object to `client.query` and the object has a `.submit` function on it, the client will pass it's PostgreSQL server connection to the object and delegate query dispatching to the supplied object... It is also how pg-cursor and pg-query-stream work" ([client.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/client.mdx), "client.query with a Submittable").

Examples from the docs: `new Query('select $1::text as name', ['brianc'])` imported from `pg`, passed to `client.query(query)`.

Constructors for the SQL text:
- `pg.Query`: `new Query(config, values, callback)`; same normalization as above ([query.js#L9-L12](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L9-L12)). Exported as `pg.Query` ([lib/index.js#L24](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/index.js#L24)).
- `pg-cursor`: `new Cursor(text, values, config)` ([packages/pg-cursor/index.js#L11-L16](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-cursor/index.js#L11-L16)). Text is the first argument. Not a config object.
- `pg-query-stream`: `new QueryStream(text, values?, config)` ([packages/pg-query-stream/src/index.ts#L25-L29](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-query-stream/src/index.ts#L25-L29)). It builds a `Cursor` with the same arguments.

Both need the JS driver connection. The docs say they are incompatible with the native bindings ([docs/pages/features/native.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/native.mdx), last paragraph).

A cursor or stream uses the extended protocol with a portal. Not confirmed from the cursor source in this research (cursor `submit` was not read).

In pipeline mode (`new Client({ pipeline: true })`), custom submittables and the `rows` option are refused with an error ([client.js#L747-L763](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L747-L763); [docs/pages/features/pipelining.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/pipelining.mdx)).

## 3. Callback form and promise form

- Callback: `client.query(text, cb)`, `client.query(text, values, cb)`, `client.query(config, cb)`. `Client.query` sets `query.callback`. If it is not a function it throws `callback is not a function` ([client.js#L686-L700](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L686-L700)). Docs: [docs/pages/features/callbacks.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/callbacks.mdx) ("pass a callback function as the last argument ... a promise will not be returned").
- Promise: with no callback, `query()` returns a `Promise` that resolves with the `Result` (client.js L688-L696). A submittable returns itself instead (L677-L678).
- `pool.query` accepts the same forms. A function as first argument is refused: `Passing a function as the first parameter to pool.query is not supported` ([packages/pg-pool/index.js#L431-L439](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-pool/index.js#L431-L439)). If `values` is a function it is used as the callback (L441-L445).
- For multi-statement simple queries the result is an array of `Result` objects (query.js L60-L71, L142). Not in the docs. Source only.

## 4. `$n` placeholders, values binding, `prepareValue`

- `pg` sends the text unchanged to the server. The server substitutes parameters. Docs: "passing your query text _unaltered_ as well as your parameters to the PostgreSQL server where the parameters are safely substituted" ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), "Parameterized query").
- Code path: `Query.prepare` sends `connection.parse({ text: this.text, name, types })`, then `connection.bind({ values: this.values, valueMapper: utils.prepareValue })` ([query.js#L213-L252](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L213-L252)). No place in that path edits `text`.
- `values[0]` binds `$1`, `values[1]` binds `$2`, and so on. The positional mapping is the PostgreSQL Bind message. `pg` does not check that the count of `$n` matches `values`. The server does. Not confirmed from a `pg` source line. The Bind semantics are in the protocol docs, "Extended Query" ([protocol-flow.html#PROTOCOL-FLOW-EXT-QUERY](https://www.postgresql.org/docs/current/protocol-flow.html#PROTOCOL-FLOW-EXT-QUERY)).
- `prepareValue` ([packages/pg/lib/utils.js#L51-L93](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/utils.js#L51-L93)):
  - `null` or `undefined` becomes `null`.
  - `Buffer` is unchanged. Other typed arrays become a `Buffer`.
  - `Date` becomes a string (local offset form, or UTC if `defaults.parseInputDatesAsUTC`).
  - An array becomes a Postgres array literal string (`arrayString`), each item converted recursively.
  - An object with `toPostgres` is called as `toPostgres(prepareValue)` and the result is converted again. Circular references throw.
  - Any other object becomes `JSON.stringify(val)`.
  - Anything else becomes `val.toString()`.
- The docs list the same rules ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), "Parameters passed as the second argument to `query()` will be converted..."). The docs call the Date rule "Custom conversion to a UTC date string". The code uses local time unless `parseInputDatesAsUTC` is set. The code is the owner. Mismatch noted.
- The `prepareValue` comment says "you can override this function" (utils.js L49).
- Identifiers cannot be parameters: "PostgreSQL does not support parameters for identifiers" ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), warning box under "Parameterized query").

## 5. Several statements in one text

Which path `pg` picks (JS client), from `Query.requiresPreparation` and `submit` ([query.js#L35-L58](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L35-L58), [L163-L181](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L163-L181)). First match wins:

1. `queryMode === 'extended'`: extended.
2. `name` is truthy: extended.
3. `rows` is truthy: extended.
4. `text` is empty: simple.
5. `values` is missing: simple.
6. `values.length > 0`: extended. An empty array `[]` is simple.

Simple path: `connection.query(this.text)` sends one `Query` message (query.js L180; [packages/pg/lib/connection.js#L178](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/connection.js#L178)).
Extended path: `Parse`, `Bind`, `Describe`, `Execute`, `Sync` (query.js L213-L252).

PostgreSQL rules, from [protocol-flow.html](https://www.postgresql.org/docs/current/protocol-flow.html):
- Section 54.2.2.1 "Multiple Statements in a Simple Query": a simple `Query` message may hold several statements separated by semicolons. They run in an implicit transaction block unless explicit transaction control is used.
- Section "Extended Query", under Parse: "The query string contained in a Parse message cannot include more than one SQL statement; else a syntax error is reported. This restriction does not exist in the simple-query protocol, but it does exist in the extended protocol."
- Section 54.2.3 (end of "Extended Query"): the simple Query message "will accept multiple SQL statements in the query string".

So with `pg`: `client.query('A; B')` works (simple). `client.query('A; B', [1])` and `client.query({ name: 'x', text: 'A; B' })` fail on the server with a syntax error.
Edge: `client.query('A; B', [])` works (simple), because `values.length` is 0.

Not in the node-postgres docs: the docs do not state the protocol choice. It is source only. The exact PostgreSQL error message text for the extended case is not confirmed here. The protocol docs only say "a syntax error".

Native client (`pg.native`) picks differently ([packages/pg/lib/native/query.js#L132-L166](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/native/query.js#L132-L166)):
- `name`: `native.prepare` then `native.execute`.
- else `values` truthy (even `[]`): `native.query(text, vals, cb)`.
- else `queryMode === 'extended'`: `native.query(text, [], cb)`.
- else `native.query(text, cb)`.
Which libpq call each maps to lives in `pg-native` and libpq. Not confirmed here. Note the `[]` difference: in the native client an empty `values` array takes the values branch. In the JS client it takes the simple branch.

## 6. Receivers that expose `query()`

- `Client`: `Client.prototype.query` ([client.js#L668](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L668)). Docs: [apis/client.mdx](https://node-postgres.com/apis/client).
- `Pool`: `pool.query(text, values, cb)` ([pg-pool/index.js#L431](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-pool/index.js#L431)). It checks out a client, calls `client.query(text, values, cb)`, and releases it. Docs: [apis/pool.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/pool.mdx), section "pool.query" (signature `pool.query(text: string, values?: any[])`). The queries doc says: "both methods support the same API. In fact, `pool.query` delegates directly to `client.query` internally" ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), intro).
  - Because `pool.query` forwards its first argument, a submittable passed to `pool.query` reaches `client.query`. The call shape is `client.query(submittable, undefined, cb)`. That the pool docs support this is not confirmed. The pool docs only show text and values.
- Pool client: `pool.connect()` returns a `Client` with `release()` ([pool.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/pool.mdx), section "pool.connect"). Same `query()`. Callback form: `pool.connect((err, client, release) => ...)` ([callbacks.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/callbacks.mdx)).
- `pg.native`: `pg.native` is a lazily built `PG` instance over the native client ([lib/index.js#L47-L69](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/index.js#L47-L69)). `native.Client.prototype.query` is at [packages/pg/lib/native/client.js#L160](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/native/client.js#L160). Docs: `const { native } = pg; const { Client, Pool } = native` ([native.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/native.mdx)). It requires the `pg-native` package. `NODE_PG_FORCE_NATIVE` makes the main `Client` the native one (lib/index.js L36-L43).
- Not confirmed: whether any other receiver (for example a `Pool` created through `pg.native.Pool`) differs from `pool.query`. By source, `pg.native.Pool` is the same `pg-pool` class bound to the native client (index.js L13-L17, L25).

## 7. Import forms of the package

`package.json` `exports` at 8.23.1: `import` goes to `./esm/index.mjs`, `require` and `default` go to `./lib/index.js` ([packages/pg/package.json](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/package.json), field `exports`).

- `require('pg')`: CJS, returns the `PG` instance (`module.exports = new PG(clientConstructor)`, [lib/index.js#L45](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/index.js#L45)). It has `Client`, `Pool`, `Query`, `Connection`, `types`, `DatabaseError`, `TypeOverrides`, `escapeIdentifier`, `escapeLiteral`, `Result`, `utils`, `defaults`, and lazy `native` (L25-L36, L47-L69).
- `const { Pool, Client } = require('pg')`: works, these are properties of that object. Shown in [callbacks.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/callbacks.mdx) and [esm.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/esm.mdx) ("const pg = require('pg'); const { Client } = pg").
- `import pg from 'pg'`: works. The ESM wrapper has `export default pg` ([packages/pg/esm/index.mjs](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/esm/index.mjs), last line).
- `import { Pool } from 'pg'`: works in the ESM build. `esm/index.mjs` has named exports `Client`, `Pool`, `Connection`, `types`, `Query`, `DatabaseError`, `escapeIdentifier`, `escapeLiteral`, `Result`, `TypeOverrides`, `defaults`. Not exported by name: `native`, `utils`. (`import pg from 'pg'` then `pg.native` still works.)
- Since which version: `pg@8.15.0` ([CHANGELOG.md#L43-L45](https://github.com/brianc/node-postgres/blob/pg@8.23.1/CHANGELOG.md#L43-L45): "Add support for esm importing. CommonJS importing is still also supported."). The ESM docs say "As of v8.15.x" and "Previously if you were using ESM you would have to use `import pg from 'pg'; const { Client } = pg`" ([esm.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/esm.mdx)). The exact export list at 8.15.0 was not read. Only the 8.23.1 list is confirmed.
- `pg.Pool`: `this.Pool = poolFactory(this.Client)` ([lib/index.js#L25](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/index.js#L25), L13-L17). It is a subclass of `pg-pool`'s `Pool`, so `new pg.Pool(...)`, `const { Pool } = pg` and `pg.Pool` all give the same class.
- `pg-pool` can also be required directly (`require('pg-pool')`). The `pg-pool` package exposes the same `query` method. Not confirmed from a `pg-pool` doc page in this research. The `Pool` class in `pg-pool/index.js` has `query` at L431.
- Namespace import `import * as pg from 'pg'` is not covered by the docs. Not confirmed.
- Native with ESM: `import pg from 'pg'; const { native } = pg` ([native.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/native.mdx)).

## 8. Other facts for a static tool that finds SQL strings

- `escapeIdentifier` and `escapeLiteral`: exported on the module (`pg.escapeIdentifier`, `pg.escapeLiteral`; ESM named exports `escapeIdentifier`, `escapeLiteral`) and as methods on `Client` ([client.js#L605-L614](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js#L605-L614); [utils.js#L179-L184](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/utils.js#L179-L184)). Docs: [docs/pages/apis/utilities.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/apis/utilities.mdx) (`import { escapeIdentifier } from 'pg'`, `import { escapeLiteral } from 'pg'`). The native `Client` class does not define them in `native/client.js` (grep found no match). Not confirmed for `native.Client`; `pg.native.escapeIdentifier` exists because `native` is a `PG` instance (lib/index.js L31-L32).
- `pg-format`: a separate npm package, not part of `pg`. The docs recommend it for dynamic identifiers: "use pg-format package for handling escaping these values" ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), warning box). Its own API (`format('%I', ...)`) is not covered by a primary source here. Not confirmed.
- A tool should not treat `pool.query` text built by string concatenation as parameterized. The docs warn against it ([queries.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/queries.mdx), "avoid string concatenating parameters into the query text directly").
- The SQL text can sit in `text` (config) or be the first argument. For `pg-cursor` and `pg-query-stream` it is the first constructor argument. For `new Query(...)` it is the first argument or `config.text`.
- Empty or missing `text`: allowed when `name` is a string (name-only reuse). Otherwise an error (query.js L152-L155).
- `types` in the config is the result-parser set (docs "Types") and also the parameter type list for `parse` ([query.js#L216-L220](https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js#L216-L220)). The docs only describe the result-parser meaning. Mismatch noted. Not confirmed which role `types` plays in `Parse` for an object with `getTypeParser`.
- Result `rows`/`fields` and `rowMode` do not change the SQL text.
- Placeholders are only `$1`, `$2`, ... (PostgreSQL). `pg` does not support `?` or `:name`. Not stated in one doc line; follows from "passing your query text unaltered" (queries.mdx) and the absence of any rewriting in `query.js`.
- `client.query` may hold a `query_timeout` (config or connection param). Does not change the text.
- Pipelining (`pipeline: true` client or pool option) changes timing only. The protocol choice stays as in point 5 ([pipelining.mdx](https://github.com/brianc/node-postgres/blob/pg@8.23.1/docs/pages/features/pipelining.mdx)).

## Sources

- node-postgres docs site: https://node-postgres.com (pages: `/features/queries`, `/apis/client`, `/apis/pool`, `/features/callbacks`, `/features/esm`, `/features/native`, `/features/pipelining`, `/apis/utilities`)
- Docs source at the tag: https://github.com/brianc/node-postgres/tree/pg@8.23.1/docs/pages
- `packages/pg/lib/client.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/client.js
- `packages/pg/lib/query.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/query.js
- `packages/pg/lib/utils.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/utils.js
- `packages/pg/lib/index.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/index.js
- `packages/pg/lib/connection.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/lib/connection.js
- `packages/pg/lib/native/client.js` and `native/query.js`: https://github.com/brianc/node-postgres/tree/pg@8.23.1/packages/pg/lib/native
- `packages/pg/esm/index.mjs`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/esm/index.mjs
- `packages/pg/package.json`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg/package.json
- `packages/pg-pool/index.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-pool/index.js
- `packages/pg-cursor/index.js`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-cursor/index.js
- `packages/pg-query-stream/src/index.ts`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/packages/pg-query-stream/src/index.ts
- `CHANGELOG.md`: https://github.com/brianc/node-postgres/blob/pg@8.23.1/CHANGELOG.md
- PostgreSQL protocol flow: https://www.postgresql.org/docs/current/protocol-flow.html (sections 54.2.2.1 "Multiple Statements in a Simple Query", "Extended Query" with the Parse note)
- Version check: npm registry `dist-tags.latest` for `pg` was `8.23.1`; the git tag `pg@8.23.1` was cloned and read.
