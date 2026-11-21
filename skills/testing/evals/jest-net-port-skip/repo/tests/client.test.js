const { createServer } = require('node:http')
const { getData } = require('../src/client')

test('reads remote data', async () => {
  const data = await getData('https://api.example.org/data')
  expect(data).toBeDefined()
})

test('reads handled data', async () => {
  const spy = jest.spyOn(globalThis, 'fetch').mockResolvedValue({ json: async () => ({ ok: true }) })
  const data = await getData('https://api.example.org/handled')
  spy.mockRestore()
  expect(data).toEqual({ ok: true })
})

test('serves on a fixed port', () => {
  const server = createServer((_, res) => res.end('x')).listen(3000)
  server.close()
  expect(server).toBeDefined()
})

test.skip('later', () => {
  expect(1).toBe(2)
})

test.todo('write this')

test('runs in order', () => {
  const log = jest.fn()
  log('a')
  log('b')
  expect(log).toHaveBeenNthCalledWith(1, 'a')
  expect(log).toHaveBeenNthCalledWith(2, 'b')
})
