import { Pool } from 'pg';

const pool = new Pool();

export async function customerNames() {
  return pool.query('SELECT id, name FROM shop.customers ORDER BY id');
}

export async function customerById(id: number) {
  return pool.query('SELECT id, name FROM shop.customers WHERE id = $1', [id]);
}
