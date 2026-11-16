import { Pool } from 'pg';

const pool = new Pool();

export async function findByName(name: string) {
  return pool.query(`SELECT id FROM users WHERE name = '${name}'`);
}

export async function findById(id: number) {
  return pool.query('SELECT id FROM users WHERE id = $1', [id]);
}
