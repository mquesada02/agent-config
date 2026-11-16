import { Pool } from 'pg';

const pool = new Pool();

export async function byName(name: string) {
  return pool.query(`SELECT id, name FROM shop.customers WHERE name = '${name}'`);
}
