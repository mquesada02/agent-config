import postgres from 'postgres';

const sql = postgres();

export async function addNote() {
  return sql`
    INSERT INTO shop.notes (body) VALUES ('hello')
  `;
}
