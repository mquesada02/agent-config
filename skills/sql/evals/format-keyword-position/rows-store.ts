import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const countRows = () => sql`
  select count(*) from rows
`

export const listRows = (sel: ReturnType<typeof sql>, id: number) => sql`
  ${sel} * from rows where id = ${id}
`
