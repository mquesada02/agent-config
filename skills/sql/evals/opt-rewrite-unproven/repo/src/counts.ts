import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function orderCounts() {
  return sql`
    SELECT u.id, (SELECT count(id) FROM orders o WHERE o.user_id = u.id) AS n FROM users u
  `;
}
