-- Seed of the `pg_run diff` Docker tests. Synthetic data only. The schema `diffs` is the only one that the tests use.
CREATE SCHEMA diffs;

CREATE TABLE diffs.t (id int PRIMARY KEY, grp int, txt text, doc json, f double precision);
INSERT INTO diffs.t
SELECT g, g % 3, 'row ' || g, ('{"k": ' || g || '}')::json, g / 3.0 FROM generate_series(1, 30) AS g;

-- Duplicate rows: the multiset difference counts them.
CREATE TABLE diffs.dups_a (v int);
INSERT INTO diffs.dups_a VALUES (1), (1), (2);
CREATE TABLE diffs.dups_b (v int);
INSERT INTO diffs.dups_b VALUES (1), (2), (2);

-- Ties: two rows share the sort key 1.
CREATE TABLE diffs.ties (id int, k int);
INSERT INTO diffs.ties VALUES (1, 1), (2, 1), (3, 2);

-- More than 20 rows.
CREATE TABLE diffs.big (id int);
INSERT INTO diffs.big SELECT generate_series(1, 100);

-- A table with 101 columns (a function call takes at most 100 arguments).
DO $wide$
BEGIN
  EXECUTE 'CREATE TABLE diffs.wide (' || (
    SELECT string_agg('c' || i || ' int', ', ' ORDER BY i) FROM generate_series(1, 101) AS i
  ) || ')';
  EXECUTE 'INSERT INTO diffs.wide SELECT ' || (
    SELECT string_agg('g + ' || i, ', ' ORDER BY i) FROM generate_series(1, 101) AS i
  ) || ' FROM generate_series(1, 3) AS g';
END
$wide$;

-- Sort key forms. The nondeterministic collation `ci` is in `public`: the key reader does not read a schema-qualified collation.
CREATE COLLATION public.ci (provider = icu, locale = 'und-u-ks-level2', deterministic = false);
CREATE TABLE diffs.words (id int PRIMARY KEY, w text, vc varchar(10));
INSERT INTO diffs.words VALUES (1, 'a', 'a'), (2, 'A', 'A'), (3, 'b', 'b'), (4, 'c', 'c');
CREATE TABLE diffs.distinct_words (id int PRIMARY KEY, w text);
INSERT INTO diffs.distinct_words VALUES (1, 'a'), (2, 'b'), (3, 'c');
CREATE DOMAIN diffs.pos AS int;
CREATE TYPE diffs.mood AS ENUM ('sad', 'ok', 'happy');
CREATE TABLE diffs.kinds (id int PRIMARY KEY, d diffs.pos, arr int[], r int4range, m diffs.mood);
INSERT INTO diffs.kinds VALUES
  (1, 1, '{1}', '[1,2)', 'sad'), (2, 2, '{2}', '[2,3)', 'ok'), (3, 3, '{3}', '[3,4)', 'happy');
CREATE TABLE diffs.owners (id int PRIMARY KEY, name text);
INSERT INTO diffs.owners VALUES (1, 'ann'), (2, 'bob');
CREATE TABLE diffs.pets (id int PRIMARY KEY, owner_id int, name text);
INSERT INTO diffs.pets VALUES (1, 1, 'cat'), (2, 1, 'dog'), (3, 2, 'eel');

CREATE SEQUENCE diffs.seq;

CREATE FUNCTION diffs.probe() RETURNS text LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'ro=% st=% lt=% idle=% tt=%',
    current_setting('default_transaction_read_only'), current_setting('statement_timeout'),
    current_setting('lock_timeout'), current_setting('idle_in_transaction_session_timeout'),
    coalesce(current_setting('transaction_timeout', true), 'unset');
END $f$;
