import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function byIds(ids: number[]) {
  return sql`
    SELECT id FROM users WHERE id IN (${sql(ids)})
  `;
}
