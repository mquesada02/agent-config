import { expect, test, vi } from 'vitest'

test('waits on the real clock', async () => {
  await new Promise((resolve) => setTimeout(resolve, 500))
  expect(1).toBe(1)
})

test('waits on a fake clock', async () => {
  vi.useFakeTimers()
  let done = false
  setTimeout(() => { done = true }, 500)
  await vi.advanceTimersByTimeAsync(500)
  vi.useRealTimers()
  expect(done).toBe(true)
})
