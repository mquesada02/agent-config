import { Pool } from "pg";

const pool = new Pool();

export async function listOrders() {
  const client = await pool.connect();
  try {
    return await client.query("select * from orders order by id");
  } finally {
    client.release();
  }
}

export function findByCustomer(name: string) {
  return pool.query({ text: "select id, total from orders where customer = $1", values: [name] });
}
