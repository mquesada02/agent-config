import postgres from 'postgres';

const sql = postgres();

export async function estimateRows() {
  return sql`
    SELECT id, kind FROM shop.events WHERE id % 3 = 0
  `;
}
