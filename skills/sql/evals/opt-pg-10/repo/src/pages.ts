import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function deepPage() {
  return sql`
    SELECT id FROM events ORDER BY id LIMIT 50 OFFSET 5000
  `;
}
