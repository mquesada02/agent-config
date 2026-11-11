import postgres from 'postgres';

const sql = postgres();

export async function rareEvents() {
  return sql`
    SELECT id, created_at FROM shop.events WHERE kind = 'rare'
  `;
}
