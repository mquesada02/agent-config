import postgres from 'postgres';

const sql = postgres();

export async function ordersPerCustomer() {
  return sql`
    SELECT c.name, COUNT(*) AS orders, SUM(o.total) AS total
    FROM shop.orders AS o
    JOIN shop.customers AS c ON c.id = o.customer_id
    GROUP BY c.name
    ORDER BY total DESC
  `;
}
