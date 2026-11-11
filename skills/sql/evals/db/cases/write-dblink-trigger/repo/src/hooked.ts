import postgres from 'postgres';

const sql = postgres();

export async function renameFirst() {
  return sql`
    UPDATE shop.hooked SET body = 'changed' WHERE id = 1
  `;
}
