# Engine-neutral SQL sources for a fallback

Ticket 913, map 912. Research date: 2026-11-20.

Question: which published, engine-neutral SQL guidance can a SQL skill use when the engine is not PostgreSQL (for example MySQL, SQLite, SQL Server)?

All sources below are primary: standards bodies, official docs, or project repos. Each claim has a URL. Where a page did not state a fact, this file says "not stated". Examples are synthetic.

Topic key used in the tables:

- STYLE = style and layout
- PARAM = parameters instead of string building
- COLS = explicit column lists (no `SELECT *`)
- INDEX = indexes for filters and joins
- MIGR = safe migrations (locks, backfills, reversible steps)
- NULL = NULL handling

## 1. ISO/IEC 9075 (the SQL standard)

- URL: https://www.iso.org/standard/76584.html (Part 2, Foundation). The ISO site blocked my fetch (HTTP 403). I used the search record and the public sample at https://cdn.standards.iteh.ai/samples/76584/aaece6c9a451487cbc2f8f6f9564a45e/ISO-IEC-9075-2-2023.pdf.
- Version and date: ISO/IEC 9075-2:2023, 6th edition, published June 2023, about 1715 pages (search record for the ISO store page, https://mbs.isolutions.iso.org/standard/76584.html). The same record shows a revision stage started 2025-06-22. I did not verify this on the ISO page.
- Access: paid. The ISO store lists CHF 221 (search record above). Only the front matter and table of contents are public in the sample.
- License for quoting: the sample says "© ISO/IEC 2023 ... no part of this publication may be reproduced or utilized otherwise in any form or by any means ... including ... posting on the internet ... without prior written permission." Do not copy standard text into the skill. Cite it by name and number only.
- What is public about portable SQL:
  - The table of contents lists "Names and identifiers" and "Lexical elements" as clauses (sample PDF above). The text of those clauses is not public.
  - Public secondary text from engine docs says what the standard requires. PostgreSQL docs say the standard folds unquoted names to upper case, and advise: "If you want to write portable applications you are advised to always quote a particular name or never quote it." (https://www.postgresql.org/docs/current/sql-syntax-lexical.html, PostgreSQL 19 docs.)
- Terms for quoting (from the engine docs that describe the standard form):
  - The standard calls the quoted form a "delimited identifier": a name in double quotes. The unquoted form is a "regular identifier". PostgreSQL docs use "delimited identifier" for the double-quote form (same URL). SQL Server docs use both terms: "Regular identifiers" and "Delimited identifiers" (https://learn.microsoft.com/en-us/sql/relational-databases/databases/database-identifiers, page dated 2026-04-08).
  - String literals use single quotes. A double quote is for names. SQLite says: `"keyword"` is an identifier and is standard; `'keyword'` is a string (https://www.sqlite.org/lang_keywords.html).
- Engine differences from the standard form:
  - MySQL quotes names with backticks. Double quotes quote names only in `ANSI_QUOTES` mode, which is off by default (https://dev.mysql.com/doc/refman/8.4/en/identifiers.html).
  - SQL Server accepts brackets and double quotes. Double quotes work only with `QUOTED_IDENTIFIER` ON (Microsoft page above).
  - SQLite accepts double quotes, brackets, and backticks. It also treats an unresolved `"name"` as a string, so a typo can return text instead of an error (SQLite page above).
- Neutrality: fully neutral by design, but not readable for free.
- Topics: STYLE no; PARAM no (the standard defines dynamic parameters, but the text is paywalled and I did not read it); COLS no; INDEX no (the standard does not define indexes: not verified, the sample has no such clause in its table of contents); MIGR no; NULL yes (three-valued logic is in the standard, but the text is paywalled: not verified).
- Use in a skill: cite the quoting terms through the engine docs above. Do not quote the standard.

## 2. sqlstyle.guide (Simon Holywell)

- URL: https://www.sqlstyle.guide/
- Version and date: no version or date on the page. The source repo https://github.com/treffynnon/sqlstyle.guide had its last commit on 2026-03-17 (GitHub API).
- License: "SQL style guide by Simon Holywell is licensed under a Creative Commons Attribution-ShareAlike 4.0 International License." (page footer). You may quote with attribution. Derived text must use the same license. The repo shows no separate license file in the GitHub API.
- Neutrality: high. It tells readers to avoid vendor functions and data types for portability. Its reserved-word appendix lists ANSI, MySQL, PostgreSQL, SQL Server, ODBC, and Oracle words (same page).
- Topics:
  - STYLE: yes. Keyword "river" alignment, spacing, AND/OR lines, join and subquery indentation, lowercase snake_case names, alias and suffix rules.
  - PARAM: no.
  - COLS: no.
  - INDEX: no.
  - MIGR: no.
  - NULL: no.
  - Also covers: data types, default values, constraints, and keys in CREATE statements.

## 3. Other style guides

All three are real, but each has a limit.

### dbt Labs SQL style guide

- URL: https://docs.getdbt.com/best-practices/how-we-style/2-how-we-style-our-sql
- Version and date: "Last updated on Oct 14, 2026." Not tied to a dbt version.
- License: page footer says "© 2026 dbt Labs, LLC. All Rights Reserved." The page states no content license. The docs repo https://github.com/dbt-labs/docs.getdbt.com has an Apache-2.0 license (GitHub API). Check that file before you copy text. Short quotes with a link are the safe use.
- Neutrality: medium. Most rules are general. The model-config example uses `sort` and `dist` keys, which are warehouse-specific. It also uses dbt `ref()` calls.
- Topics: STYLE yes (4-space indent, 80 columns, lowercase keywords, trailing commas, explicit `as`, explicit join type, prefix columns when joining, `union all` over `union`, CTE layout). COLS partly: it allows `select *` only in the final CTE line and says to select only needed columns in import CTEs. PARAM no. INDEX no. MIGR no. NULL no.

### Mozilla data docs SQL style guide

- URL: https://docs.telemetry.mozilla.org/concepts/sql_style.html
- Version and date: not stated.
- License: not stated on the page. The repo https://github.com/mozilla/data-docs is MPL-2.0 (GitHub API).
- Neutrality: low. Examples target BigQuery Standard SQL and Presto. The page says some behavior varies by engine.
- Topics: STYLE yes (upper-case keywords, explicit join type, `JOIN ... ON` instead of comma joins, CTEs over subqueries, comma placement). COLS no rule. PARAM no. INDEX no. MIGR no. NULL no.

### GitLab handbook SQL style guide

- URL: https://handbook.gitlab.com/handbook/enterprise-data/platform/sql-style-guide/
- I could not read the body. The page is 230,000 characters and the fetch returned only the navigation menu. I did not read the rest. Treat as unreviewed.

## 4. SQLFluff (multi-dialect linter and formatter)

- URLs: https://docs.sqlfluff.com/en/stable/reference/dialects.html, https://docs.sqlfluff.com/en/stable/reference/rules.html, https://github.com/sqlfluff/sqlfluff
- Version and date: 4.5.0, uploaded to PyPI 2026-10-30 (https://pypi.org/pypi/sqlfluff/json). The docs page says only "stable".
- License: MIT (PyPI record above and GitHub API). Quoting the docs is fine with attribution. The docs' own license is not stated on the pages I read.
- Dialects: 28, listed at the dialects URL. They include `ansi`, `mysql`, `mariadb`, `sqlite`, `tsql`, `postgres`, `oracle`, `snowflake`, `bigquery`, `duckdb`, `db2`, `redshift`, `trino`, and others. The `ansi` dialect is the neutral base.
- Rules: 79 rules in 11 groups (rules URL). Groups: Aliasing 10, Ambiguous 9, Capitalisation 5, Convention 13, Jinja 1, Layout 15, Oracle 1, Postgres 2, References 7, Structure 12, T-SQL 4. Only the Oracle, Postgres, and T-SQL groups are engine-specific.
- Rules relevant to the topics (from https://docs.sqlfluff.com/en/stable/reference/rules/ambiguous.html and https://docs.sqlfluff.com/en/stable/reference/rules/convention.html):
  - COLS: AM04 `ambiguous.column_count` flags queries such as `SELECT *` that return an unknown number of columns. Not auto-fixable. CV13 is the opposite rule (final `SELECT *` of a CTE) and is off by default.
  - NULL: CV05 `convention.is_null` requires `IS` / `IS NOT` for NULL tests. CV02 `convention.coalesce` prefers `COALESCE` over `IFNULL` or `NVL`.
  - STYLE: Layout (LT), Capitalisation (CP), Aliasing (AL), CV01 (`!=` or `<>`), CV06 (terminator), CV12 (join conditions in `ON`), AM05 (explicit join type), AM09 (`LIMIT` without `ORDER BY`).
  - Quoting: CV10 checks quoted literals only. It does not check quoted identifiers.
  - Other: RF group checks references. Not read in detail.
- Topics: STYLE yes; PARAM no rule for it, but the placeholder templater exists (not verified in this research); COLS yes (AM04); INDEX no; MIGR no; NULL yes (CV05, CV02).
- Neutrality: high for the `ansi` dialect and for rules outside the three engine groups. The user must set the right `dialect`, or parsing can fail.

## 5. sqlfmt

- URL: https://github.com/tconbeer/sqlfmt
- Version and date: 0.32.0, uploaded 2026-08-10 (PyPI package `shandy-sqlfmt`, https://pypi.org/pypi/shandy-sqlfmt/json).
- License: Apache-2.0 (LICENSE file at https://raw.githubusercontent.com/tconbeer/sqlfmt/main/LICENSE and PyPI record). The GitHub API returned no license label.
- Neutrality: high. It runs in a "polyglot" mode that works with nearly all dialects. ClickHouse needs `--dialect clickhouse` because it is case-sensitive. It lexes SQL and does not parse a full grammar.
- Limits from the README: formats only `select`, `delete`, `grant`, `revoke`, and `create function` statements. Line length is the only option (default 88). It is not a linter. The README warns "It might even break your SQL syntax", so run it on files under version control.
- Topics: STYLE yes (layout only). PARAM, COLS, INDEX, MIGR, NULL: no.

## 6. sql-formatter

- URL: https://github.com/sql-formatter-org/sql-formatter
- Version and date: 15.10.0, 2026-11-20 (npm registry, https://registry.npmjs.org/sql-formatter).
- License: MIT (npm record and GitHub API).
- Dialects: BigQuery, ClickHouse, DB2, DuckDB, Hive, MariaDB, MySQL, TiDB, N1QL, PL/SQL, PostgreSQL, Redshift, SingleStoreDB, Snowflake, Spark, SQL Server (T-SQL), Trino/Presto. The CLI also takes DB2 for i, SQLite, and generic `sql`.
- Parameters: it replaces placeholders in prepared statements through the `params` option, and `paramTypes` sets the placeholder types. It formats text. It does not check that code uses parameters.
- Topics: STYLE yes (layout only). Others: no.
- Neutrality: high, with one setting per dialect.

## 7. OWASP SQL Injection Prevention Cheat Sheet

- URL: https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- Version and date: no date on the page. The source repo https://github.com/OWASP/CheatSheetSeries had a commit on 2026-11-19 (GitHub API).
- License: CC BY-SA 4.0 (page footer and GitHub API). You may quote with attribution and a same-license rule for derived text.
- Content:
  - Primary defense: bound parameters. Keep the SQL structure apart from data values.
  - Stored procedures: binding the call does not protect dynamic SQL built inside the procedure.
  - Allow-list: table names, column names, and sort direction cannot be bound. Map user choices to fixed values owned by the application.
  - Escaping by hand: strongly discouraged, because rules vary by dialect and configuration.
  - Extra: least privilege, separate accounts, views to limit columns.
  - Quoting identifiers: the page says PostgreSQL's `format('%I', ...)` quotes identifiers, and that quoting does not limit which tables the application can reach. Use fixed mappings anyway.
- Neutrality: medium. The principle is neutral. The code examples are Java/JDBC, Hibernate, PostgreSQL, MySQL (`NO_BACKSLASH_ESCAPES`), PHP PDO, and Microsoft.
- Topics: PARAM yes (core topic). STYLE no. COLS no (it mentions views to limit columns only). INDEX no. MIGR no. NULL no.

## 8. OWASP Query Parameterization Cheat Sheet

- URL: https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html
- Version and date: no date on the page. It cites the OWASP Top 10:2025, so it is at least that recent. Same repo and commit date as above.
- License: CC BY-SA 4.0.
- Content: prepared statements in Java (JDBC, JPA, Hibernate), .NET, Ruby, PHP PDO, ColdFusion, Perl DBI, Rust SQLx, and stored procedures in Oracle PL/SQL and SQL Server T-SQL. It says parameterization must run server-side: "Please ensure that query parameterization is done server-side!"
- It does not say whether names of tables or columns can be bound. Use the other cheat sheet for that.
- Neutrality: low for code, high for the principle.
- Topics: PARAM yes. All others: no.

## 9. Use The Index, Luke (Markus Winand)

- URL: https://use-the-index-luke.com/
- Version and date: copyright "2010-2026". No edition date on the page.
- License: all rights reserved. The page shows "Copyright 2010-2026 Markus Winand." It links a Legal page that I did not read. Do not copy text. Link and paraphrase only.
- Neutrality: high. It "presents indexing in a vendor agnostic fashion", with notes per product. Tested engines: Db2 LUW, MySQL, Oracle, PostgreSQL, SQL Server (same page).
- Topics: INDEX yes (B-trees, WHERE-clause predicates, ranges, `LIKE`, joins, sorting, paging, effects on writes). NULL partly (NULL in indexed predicates, listed in the table of contents). Others: no.

## 10. Evolutionary Database Design (Fowler and Sadalage)

- URL: https://martinfowler.com/articles/evodb.html
- Version and date: original January 2003, revised May 2016.
- License: "© Martin Fowler". The page states no reuse terms in the content I read. Link and paraphrase only.
- Content: small migrations are easier to get right and to reverse. A "transition phase" lets old and new schema work together (the same idea as expand and contract). Use a view or trigger for old access, then remove it. Run the data migration in the same script as the schema change. Example: add a default, fill existing NULLs, then add `NOT NULL`.
- Neutrality: medium. Examples use Oracle types. The tools named (Flyway, Liquibase) are general.
- Topics: MIGR partly: small steps, reversibility, backfills yes; locks no. NULL only as a migration step. Others: no.

## Engine docs used for quoting terms

These are engine-specific. Use them only to show how each engine differs from the standard form.

| Engine | URL | Version or date |
| --- | --- | --- |
| PostgreSQL | https://www.postgresql.org/docs/current/sql-syntax-lexical.html | 19.0 docs, copyright 1996-2026 |
| MySQL | https://dev.mysql.com/doc/refman/8.4/en/identifiers.html | 8.4 |
| SQLite | https://www.sqlite.org/lang_keywords.html | version not stated on the page |
| SQL Server | https://learn.microsoft.com/en-us/sql/relational-databases/databases/database-identifiers | ms.date 2026-04-08 |

## Coverage table

Y = covers it. P = covers it in part. Blank = does not cover it.

| Source | STYLE | PARAM | COLS | INDEX | MIGR | NULL | Neutral | License for quoting |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ISO/IEC 9075 | | | | | | P (paywalled) | full | no copying |
| sqlstyle.guide | Y | | | | | | high | CC BY-SA 4.0 |
| dbt style guide | Y | | P | | | | medium | not stated on page |
| Mozilla style guide | Y | | | | | | low | not stated on page |
| SQLFluff | Y | | Y (AM04) | | | Y (CV05, CV02) | high (`ansi`) | MIT |
| sqlfmt | Y | | | | | | high | Apache-2.0 |
| sql-formatter | Y | | | | | | high | MIT |
| OWASP SQLi Prevention | | Y | | | | | medium | CC BY-SA 4.0 |
| OWASP Query Param. | | Y | | | | | low (code) | CC BY-SA 4.0 |
| Use The Index, Luke | | | | Y | | P | high | all rights reserved |
| Evolutionary DB Design | | | | | P | P | medium | all rights reserved |

## Answer

Sources to use as the fallback, with the topics each one covers:

1. SQLFluff, `ansi` dialect, with the user's `dialect` set when known (MIT). Covers STYLE, COLS (AM04), NULL (CV05, CV02). Use it as a tool and as the rule catalogue. Cite rule codes. Do not enable the Postgres, Oracle, or T-SQL groups on a different engine.
2. sqlstyle.guide (CC BY-SA 4.0). Covers STYLE and neutral naming. Quote with attribution.
3. OWASP SQL Injection Prevention and Query Parameterization cheat sheets (CC BY-SA 4.0). Cover PARAM, the allow-list rule for identifiers, and the warning against manual escaping.
4. Use The Index, Luke (link only, no copying). Covers INDEX for filters and joins across five engines.
5. Evolutionary Database Design (link only). Covers MIGR: small reversible steps, transition phase, backfill before `NOT NULL`.
6. sqlfmt or sql-formatter, as optional formatters. They cover STYLE layout only. Use sqlfmt only for the statement kinds it supports. Use sql-formatter when the engine is MySQL, SQLite, SQL Server, or similar and the user wants a formatter.
7. ISO/IEC 9075 for the terms only: "delimited identifier" (double quotes), "regular identifier" (unquoted), single quotes for strings. Take the advice from the PostgreSQL docs: quote a name always or never. Then show each engine's quoting form from its own docs (MySQL backticks, SQL Server brackets or double quotes, SQLite double quotes).

### Gaps

No neutral source covers these topics well:

- Locks during migrations. Fowler covers step size and backfills. No neutral source says which statements lock a table, for how long, or how to avoid it. Each engine documents this in its own manual, and the answer differs by engine and version.
- Batched backfills for large tables (batch size, throttling, resume). Not covered by any source above.
- Reversible migrations in detail. Fowler says automated reverse migrations were not cost-effective. No source gives a neutral rule for when to write a down step.
- Explicit column lists as a rule with reasons. Only SQLFluff AM04 states it, and only as a lint check. The dbt guide allows `select *` in the final CTE.
- NULL handling as guidance (three-valued logic, `NOT IN` with NULL, NULL in unique indexes, NULL in aggregates). SQLFluff has two lint rules. The standard defines the behavior, but its text is paywalled. Engines differ on unique indexes with NULL (not verified here).
- Parameters in each driver and engine: placeholder syntax (`?`, `$1`, `:name`, `@name`) differs by engine and driver. OWASP gives examples for some drivers only.
- Identifier binding. OWASP says to allow-list. No neutral source gives a safe quoting function for all engines.
- Index rules for engine-specific features (partial, covering, and expression indexes) and for write cost on MySQL, SQLite, or SQL Server specifically. Use The Index, Luke covers the neutral base only.
- Free, quotable text of the SQL standard. No public source exists. Use engine docs as proxies.
- GitLab handbook SQL style guide: not read, so not assessed.
