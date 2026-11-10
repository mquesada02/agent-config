import postgres from 'postgres';

const sql = postgres();

export async function customersWithoutLaterEmail(lastId: number) {
  return sql`
    SELECT c.id, c.name
    FROM shop.customers AS c
    WHERE c.email NOT IN (SELECT n.email FROM shop.customers AS n WHERE n.id > ${lastId})
  `;
}
