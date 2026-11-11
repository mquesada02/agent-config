import postgres from 'postgres';

const sql = postgres();

export async function ordersPerCustomer() {
  return sql`
    SELECT c.id, c.name, (SELECT count(*) FROM shop.orders AS o WHERE o.customer_id = c.id) AS orders
    FROM shop.customers AS c
  `;
}
