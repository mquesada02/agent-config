import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const listNotes = (owner: number) => sql`select id, body from notes where owner_id = ${owner} order by id`
