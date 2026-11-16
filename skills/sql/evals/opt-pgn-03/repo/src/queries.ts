import { Pool } from 'pg';

const pool = new Pool();

export async function byPair(a: number, b: number) {
  return pool.query('SELECT id FROM users WHERE a = $1 AND b = $2', [a]);
}

export async function byPairBoth(a: number, b: number) {
  return pool.query('SELECT id FROM users WHERE a = $1 AND b = $2', [a, b]);
}
