import postgres from 'postgres';

const sql = postgres(process.env.DATABASE_URL ?? '');

export async function byIds(ids: number[]) {
  return sql`
    SELECT id FROM users WHERE id IN ${sql(ids)}
  `;
}

export async function search(role?: string) {
  return sql`
    SELECT id FROM users WHERE active = true ${role ? sql`AND role = ${role}` : sql``}
  `;
}

export async function unbanned() {
  return sql`
    SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM bans)
  `;
}

export async function liveTeams() {
  return sql`
    SELECT id FROM teams WHERE id NOT IN (SELECT id FROM archived_teams)
  `;
}

export async function fiveUnits() {
  return sql`
    SELECT id FROM stock WHERE qty = 5
  `;
}
