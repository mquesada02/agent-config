import postgres from 'postgres';

const sql = postgres();

export async function firstOrders() {
  return sql`
    SELECT g.n, x.id FROM generate_series(1, 2000) AS g(n) CROSS JOIN LATERAL (SELECT o.id FROM shop.orders AS o WHERE o.customer_id = (g.n % 20) + 1 LIMIT 1) AS x
  `;
}
