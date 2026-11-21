import { expect, test, vi } from 'vitest'

test.skip('later', () => {
  expect(1).toBe(2)
})

test.skipIf(process.platform === 'win32')('unix only', () => {
  expect(1).toBe(1)
})

test.todo('write this')

test('runs in order', () => {
  const first = vi.fn()
  const second = vi.fn()
  first()
  second()
  expect(first).toHaveBeenCalledBefore(second)
})
