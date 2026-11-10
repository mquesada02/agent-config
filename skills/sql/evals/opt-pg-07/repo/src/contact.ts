import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function byContact(value: string) {
  return sql`
    SELECT id FROM users WHERE email = ${value} OR phone = ${value}
  `;
}
