import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function endsWith() {
  return sql`
    SELECT id FROM users WHERE name LIKE '%son'
  `;
}
