import postgres from 'postgres';

const sql = postgres();

export async function discountFebruaryOrders() {
  return sql`
    UPDATE shop.orders SET total = total * 0.9 WHERE date_trunc('month', placed_on) = DATE '2026-02-01'
  `;
}
