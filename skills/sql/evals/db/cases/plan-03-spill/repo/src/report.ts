import postgres from 'postgres';

const sql = postgres();

export async function sortedEvents() {
  return sql`
    SELECT id, payload FROM shop.events ORDER BY created_at
  `;
}
