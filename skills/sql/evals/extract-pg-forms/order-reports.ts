import pg, { Client, Pool, Query } from 'pg';
import Cursor from 'pg-cursor';
import QueryStream from 'pg-query-stream';
import { shared } from './shared';

const pool = new Pool();
const client = new pg.native.Client();
const LIST = 'SELECT id, name FROM item';
const BY_ID =
  'SELECT * FROM item ' +
  'WHERE id = $1';
const OPTIONS = { text: 'SELECT 1 FROM item' };
let mutable = 'SELECT 2 FROM item';

export class Reports {
  private db = new Pool();

  async run(id: number, table: string) {
    pool.query('SELECT 3');
    pool.query(`SELECT 4`);
    pool.query({ text: 'SELECT 5', values: [id], name: 'q5' });
    pool.query(new Query('SELECT 6'));
    pool.query(new Cursor('SELECT 7'));
    pool.query(new QueryStream('SELECT 8'));
    pool.query(LIST);
    pool.query(BY_ID, [id]);
    pool.query('SELECT 9 ' + 'FROM item');
    pool.query('SELECT * FROM ' + table);
    pool.query(`SELECT * FROM ${table}`);
    pool.query(mutable);
    pool.query(shared);
    pool.query(OPTIONS);
    this.db.query('SELECT 10');
  }
}

async function connected(table: string) {
  const lease = await pool.connect();
  lease.query('SELECT 11');
  pool.connect().then((c) => c.query('SELECT 12'));
  pool.connect((err, c) => {
    c.query('SELECT 13');
  });
  client.query(buildQuery(table));
  client.query(table);
}

const plain = new Client();
const nativePool = new pg.native.Pool();
plain.query('SELECT 14');
nativePool.query('SELECT 15');
