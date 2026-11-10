-- Synthetic seed schema for the DB eval cases. All names and values are invented.
CREATE SCHEMA shop;

CREATE TABLE shop.customers (
  id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  email text
);

CREATE TABLE shop.orders (
  id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id integer NOT NULL REFERENCES shop.customers (id),
  total numeric(10, 2) NOT NULL,
  placed_on date NOT NULL
);

CREATE TABLE shop.order_items (
  id serial PRIMARY KEY,
  order_id integer NOT NULL REFERENCES shop.orders (id),
  sku text NOT NULL,
  quantity integer NOT NULL
);

CREATE INDEX orders_customer_id_idx ON shop.orders (customer_id);

INSERT INTO shop.customers (name, email)
SELECT 'Customer ' || n, 'customer' || n || '@example.invalid' FROM generate_series(1, 20) AS n;

INSERT INTO shop.orders (customer_id, total, placed_on)
SELECT 1 + (n % 20), (n * 7 % 100) + 0.5, DATE '2026-01-01' + (n % 90) FROM generate_series(1, 200) AS n;

INSERT INTO shop.order_items (order_id, sku, quantity)
SELECT 1 + (n % 200), 'SKU-' || (n % 15), 1 + (n % 4) FROM generate_series(1, 500) AS n;
