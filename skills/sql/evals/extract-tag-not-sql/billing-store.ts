import postgres from 'postgres';

const db = postgres(process.env.DATABASE_URL ?? '');

// Old query kept for reference: sql`SELECT 1`
const note = 'run sql`SELECT 2` by hand';

export async function listInvoices(customerId: number) {
  return db`
    SELECT id, total
    FROM invoices
    WHERE customer_id = ${customerId}
  `;
}

export class InvoiceStore {
  private db: ReturnType<typeof postgres>;

  constructor(url: string) {
    this.db = postgres(url);
  }

  async paid() {
    return this.db`
      SELECT id FROM invoices WHERE paid
    `;
  }
}

export async function transfer(from: number, to: number, amount: number) {
  await db.begin(async tx => {
    await tx`UPDATE accounts SET balance = balance - ${amount} WHERE id = ${from}`;
    await tx`UPDATE accounts SET balance = balance + ${amount} WHERE id = ${to}`;
  });
}
