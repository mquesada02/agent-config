import { expect, test, vi } from 'vitest'

test('sets a mode', () => {
  process.env.MODE = 'fast'
  expect(process.env.MODE).toBe('fast')
})

test('stubs a mode', () => {
  vi.stubEnv('MODE', 'slow')
  expect(process.env.MODE).toBe('slow')
  vi.unstubAllEnvs()
})
