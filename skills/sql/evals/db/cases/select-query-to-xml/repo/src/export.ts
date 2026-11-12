import postgres from 'postgres';

const sql = postgres();

export async function customersAsXml() {
  return sql`
    SELECT query_to_xml('SELECT id, name FROM shop.customers', true, true, '') AS doc
  `;
}
