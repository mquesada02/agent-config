import { Pool } from 'pg';

const pool = new Pool();

export async function ordersOn(day: Date) {
  return pool.query('SELECT id FROM shop.orders WHERE placed_on = $1', [day]);
}
