import postgres from 'postgres';

const sql = postgres();

export async function readOnlyOff() {
  return sql`
    SELECT set_config('default_transaction_read_only', 'off', false) AS read_only
  `;
}
