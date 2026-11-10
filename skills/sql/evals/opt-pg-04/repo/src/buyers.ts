import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function buyers() {
  return sql`
    SELECT DISTINCT u.id FROM users u JOIN orders o ON o.user_id = u.id
  `;
}
