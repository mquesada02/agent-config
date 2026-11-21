import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function profile(id: number) {
  return sql`
    SELECT * FROM users WHERE id = ${id}
  `;
}
