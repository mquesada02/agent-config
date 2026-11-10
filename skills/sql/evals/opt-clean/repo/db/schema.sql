CREATE TABLE users (
  id serial PRIMARY KEY,
  role text NOT NULL,
  active boolean NOT NULL
);

CREATE TABLE bans (
  id serial PRIMARY KEY,
  user_id integer NOT NULL
);

CREATE TABLE teams (
  id serial PRIMARY KEY
);

CREATE TABLE archived_teams (
  id integer PRIMARY KEY
);

CREATE TABLE stock (
  id serial PRIMARY KEY,
  qty integer NOT NULL
);
