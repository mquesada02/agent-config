import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function profile(id: number) {
  return sql`
    select * from users where id = ${id}
  `;
}
