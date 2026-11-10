import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const listItems = (extra: boolean) => sql`
  SELECT *
  FROM items ${extra ? sql`WHERE flagged` : sql``}
`
