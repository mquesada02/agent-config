import mysql from 'mysql2/promise';

const pool = mysql.createPool(process.env.DATABASE_URL ?? '');

export async function customerNames() {
  const [rows] = await pool.query('select id, name from customers order by name');
  return rows;
}
