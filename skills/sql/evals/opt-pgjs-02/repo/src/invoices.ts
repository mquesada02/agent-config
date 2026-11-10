import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function dueOn(day: Date) {
  return sql`
    SELECT id FROM invoices WHERE due_on = ${day}::date
  `;
}
