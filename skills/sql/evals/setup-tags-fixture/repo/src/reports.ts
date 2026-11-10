import postgres from 'postgres'

const sql = postgres('postgres://localhost/example')

export class ReportStore {
  sql = postgres('postgres://localhost/example')

  ordersByIds(ids: number[]) {
    return this.sql`
      select
        o.id,
        o.total
      from orders o
      where
        o.id in ${ids}
    `
  }

  customersByName() {
    return this.sql`
      select
        c.id,
        c.name
      from customers c
      where
        c.name like '%corp'
      order by
        c.name
    `
  }

  async closeDay(day: string) {
    return sql.begin(async (tx) => {
      return tx`
        select *
        from orders
        where
          day = ${day}
      `
    })
  }
}
