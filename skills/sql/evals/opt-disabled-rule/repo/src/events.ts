import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function page() {
  return sql`
    SELECT * FROM events ORDER BY id LIMIT 50 OFFSET 5000
  `;
}
