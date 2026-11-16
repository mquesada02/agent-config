import pg from 'pg'

const pool = new pg.Pool()

export const listOrders = (customerId: number) =>
  pool.query(
    'select id, total, placed_at from orders ' +
      'where customer_id = $1 ' +
      'order by placed_at desc',
    [customerId],
  )

export const countOrders = () => pool.query('select count(*) from orders')
