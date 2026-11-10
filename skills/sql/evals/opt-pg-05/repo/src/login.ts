import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function byEmail(email: string) {
  return sql`
    SELECT id FROM users WHERE lower(email) = ${email}
  `;
}
