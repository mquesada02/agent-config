import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function since(when: Date) {
  return sql`
    SELECT id FROM invoices WHERE created_at > ${when}
  `;
}
