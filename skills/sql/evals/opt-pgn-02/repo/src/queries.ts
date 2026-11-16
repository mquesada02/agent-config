import { Pool } from 'pg';

const pool = new Pool();

export async function logAndClean(msg: string) {
  return pool.query('INSERT INTO logs (msg) VALUES ($1); DELETE FROM tmp', [msg]);
}

export async function logOnly(msg: string) {
  return pool.query('INSERT INTO logs (msg) VALUES ($1)', [msg]);
}
