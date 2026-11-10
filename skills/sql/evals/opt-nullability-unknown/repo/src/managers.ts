import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function nonManagers() {
  return sql`
    SELECT id FROM users WHERE id NOT IN (SELECT manager_id FROM teams)
  `;
}
