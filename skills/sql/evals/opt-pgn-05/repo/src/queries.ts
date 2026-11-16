import { Pool } from 'pg';

const pool = new Pool();

export async function byId(id: number) {
  return pool.query({ name: 'get-user', text: 'SELECT id FROM users WHERE id = $1', values: [id] });
}

export async function byEmail(email: string) {
  return pool.query({ name: 'get-user', text: 'SELECT id FROM users WHERE email = $1', values: [email] });
}

export async function byName(name: string) {
  return pool.query({ name: 'get-user-by-name', text: 'SELECT id FROM users WHERE name = $1', values: [name] });
}
