import { Pool } from 'pg';

const pool = new Pool();

export async function dueOn(day: Date) {
  return pool.query('SELECT id FROM invoices WHERE due_on = $1::date', [day]);
}

export async function dueOnText(day: string) {
  return pool.query('SELECT id FROM invoices WHERE due_on = $1::date', [day]);
}
