import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function search(role?: string) {
  return sql`
    SELECT id FROM users ${role ? sql`WHERE role = ${role}` : sql``} AND active = true
  `;
}
