import pg from 'pg'

const pool = new pg.Pool()

export const listUsers = () =>
  pool.query(
    'select id, name from users ' +
      // active users only
      'where active order by name',
  )

export const countUsers = () => pool.query('select count(*) from users')
