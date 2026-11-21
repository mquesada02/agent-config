import mysql from 'mysql2/promise';

const pool = mysql.createPool(process.env.DATABASE_URL ?? '');

export async function report(id: number) {
  const [rows] = await pool.query('select u.id, u.name from users u where u.id = ? and u.active = 1', [id]);
  return rows;
}
