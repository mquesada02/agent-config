CREATE TABLE widgets (
  id INT NOT NULL,
  name VARCHAR(80) NOT NULL,
  PRIMARY KEY (id)
);

SELECT
  id,
  name
FROM
  widgets
WHERE
  id = 1;
