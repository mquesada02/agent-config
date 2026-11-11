import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const ordersByCustomer = (customerId: number) => sql`
  SELECT
    o.id AS order_id,
    o.total AS order_total
  FROM orders AS o
  WHERE
    o.customer_id = ${customerId}
`

export const openOrders = () => sql`
  SELECT
    o.id AS order_id,
    o.created_at AS created
  FROM orders AS o
  WHERE
    o.closed_at IS NULL
  ORDER BY
    o.created_at
`

export const customersByCity = (city: string) => sql`
  SELECT
    c.id AS customer_id,
    c.name AS customer_name
  FROM customers AS c
  WHERE
    c.city = ${city}
`
