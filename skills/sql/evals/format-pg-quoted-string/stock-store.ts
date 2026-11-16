import pg from 'pg'

const pool = new pg.Pool()

export const listWarehouses = () =>
  pool.query('select id, name from warehouses order by name')

export const listStock = (warehouseId: number) =>
  pool.query('select sku, qty from stock where warehouse_id = $1 and qty < 5 order by sku', [warehouseId])
