import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { getData } from '../src/client.js'

test('reads remote data', async () => {
  const data = await getData('https://api.example.org/data')
  assert.ok(data)
})

test('reads handled data', async () => {
  mock.method(globalThis, 'fetch', async () => ({ json: async () => ({ ok: true }) }))
  const data = await getData('https://api.example.org/handled')
  mock.restoreAll()
  assert.deepEqual(data, { ok: true })
})

test('serves on a fixed port', () => {
  const server = createServer((_, res) => res.end('x')).listen(3000)
  server.close()
  assert.ok(server)
})

test('later', { skip: true }, () => {
  assert.equal(1, 2)
})

test('write this', { todo: true })

test('runs in order', () => {
  const log = mock.fn()
  log('a')
  log('b')
  assert.equal(log.mock.calls[0].arguments[0], 'a')
  assert.equal(log.mock.calls[1].arguments[0], 'b')
})
