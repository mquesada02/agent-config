import postgres from 'postgres'

const db = postgres('postgres://localhost/example')

export const listWarehouses = () => db`
  select id, name from warehouses order by name
`

export const listStock = (warehouseId: number, onlyLow: boolean) => db`
  select s.sku, s.qty, w.name as warehouse
    from stock s join warehouses w on w.id = s.warehouse_id
    where s.warehouse_id = ${warehouseId}
    ${onlyLow ? db`and s.qty < 5` : db``}
    order by s.sku
`

export const countSkus = () => db`
  select count(*) from stock
`
