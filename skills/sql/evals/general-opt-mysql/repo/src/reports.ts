import mysql from 'mysql2/promise';

const pool = mysql.createPool(process.env.DATABASE_URL ?? '');

export async function report(id: number) {
  const [rows] = await pool.query('SELECT * FROM users WHERE id = ?', [id]);
  return rows;
}
