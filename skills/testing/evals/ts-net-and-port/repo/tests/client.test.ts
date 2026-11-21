import { expect, test } from 'vitest'
import { createServer } from 'node:http'
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'
import { getData } from '../src/client'

test('reads remote data', async () => {
  const data = await getData('https://api.example.org/data')
  expect(data).toBeDefined()
})

test('reads handled data', async () => {
  const server = setupServer(http.get('https://api.example.org/handled', () => HttpResponse.json({ ok: true })))
  server.listen({ onUnhandledRequest: 'error' })
  const data = await getData('https://api.example.org/handled')
  server.close()
  expect(data).toEqual({ ok: true })
})

test('serves on a fixed port', () => {
  const server = createServer((_, res) => res.end('x')).listen(3000)
  server.close()
  expect(server).toBeDefined()
})
