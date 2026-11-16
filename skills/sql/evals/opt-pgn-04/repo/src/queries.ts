import { Pool } from 'pg';

const pool = new Pool();

export async function byIds(ids: number[]) {
  return pool.query('SELECT id FROM users WHERE id IN ($1)', [ids]);
}

export async function byIdsAny(ids: number[]) {
  return pool.query('SELECT id FROM users WHERE id = ANY($1)', [ids]);
}
