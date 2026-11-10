import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export const listWarehouses = () => sql`
  select id, name from warehouses order by name
`

export const listStock = (warehouseId: number, onlyLow: boolean) => sql`
  select s.sku, s.qty, w.name as warehouse
    from stock s join warehouses w on w.id = s.warehouse_id
    where s.warehouse_id = ${warehouseId}
    ${onlyLow ? sql`and s.qty < 5` : sql``}
    order by s.sku
`

export const countSkus = () => sql`
  select count(*) from stock
`
