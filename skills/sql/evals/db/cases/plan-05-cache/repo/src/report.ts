import postgres from 'postgres';

const sql = postgres();

export async function payloadCount() {
  return sql`
    SELECT count(payload) FROM shop.events
  `;
}
