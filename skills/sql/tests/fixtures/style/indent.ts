import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const one = () => sql`
    select a
        from t
`

export const two = () => sql`
    select b
        from u
`

export const three = () => sql`
    select c
        from v
`
