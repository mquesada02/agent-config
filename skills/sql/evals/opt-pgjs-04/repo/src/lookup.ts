import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function byName(name: string) {
  return sql.unsafe(`SELECT id FROM users WHERE name = '${name}'`);
}
