import postgres from 'postgres';

export class ProfileStore {
  private sql: ReturnType<typeof postgres>;

  constructor(url: string) {
    this.sql = postgres(url);
  }

  async profile(id: number) {
    return this.sql`
      SELECT * FROM users WHERE id = ${id}
    `;
  }
}
