import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function revenue() {
  return sql`
    SELECT SUM(o.total) FROM orders o JOIN order_items i ON i.order_id = o.id
  `;
}
