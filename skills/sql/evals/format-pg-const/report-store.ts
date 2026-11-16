import pg from 'pg'

const pool = new pg.Pool()

const LOW_STOCK = 'select sku, qty from stock where qty < 5 order by sku'

export const lowStock = () => pool.query(LOW_STOCK)

export const lowStockCount = async () => {
  const result = await pool.query(LOW_STOCK)
  return result.rowCount
}
