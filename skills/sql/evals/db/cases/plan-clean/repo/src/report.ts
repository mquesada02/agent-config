import postgres from 'postgres';

const sql = postgres();

export async function oneCustomer() {
  return sql`
    SELECT id, name FROM shop.customers WHERE id = 7
  `;
}
