SELECT
  u.id,
  u.name
FROM users AS u
WHERE u.active
  AND u.age > 3;

SELECT
  o.id,
  o.total
FROM orders AS o
JOIN users AS u ON u.id = o.user_id;

SELECT
  1
FROM t AS x;
