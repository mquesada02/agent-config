CREATE TABLE users (
  id serial PRIMARY KEY,
  email text NOT NULL,
  phone text,
  name text NOT NULL,
  role text NOT NULL,
  active boolean NOT NULL
);

CREATE TABLE orders (
  id serial PRIMARY KEY,
  user_id integer NOT NULL,
  total numeric NOT NULL
);

CREATE TABLE order_items (
  id serial PRIMARY KEY,
  order_id integer NOT NULL,
  sku text NOT NULL
);

CREATE TABLE teams (
  id serial PRIMARY KEY,
  manager_id integer
);

CREATE TABLE stock (
  id serial PRIMARY KEY,
  qty integer NOT NULL
);

CREATE TABLE invoices (
  id serial PRIMARY KEY,
  due_on date NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE events (
  id serial PRIMARY KEY,
  kind text NOT NULL
);
