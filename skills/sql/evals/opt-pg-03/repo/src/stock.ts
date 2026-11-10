import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function halfUnits() {
  return sql`
    SELECT id FROM stock WHERE qty = 5.5::numeric
  `;
}
