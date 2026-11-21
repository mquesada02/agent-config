import { test, mock } from 'node:test'
import assert from 'node:assert/strict'

test('waits on the real clock', async () => {
  await new Promise((resolve) => setTimeout(resolve, 500))
  assert.equal(1, 1)
})

test('waits on a fake clock', () => {
  mock.timers.enable({ apis: ['setTimeout'] })
  let done = false
  setTimeout(() => { done = true }, 500)
  mock.timers.tick(500)
  mock.timers.reset()
  assert.equal(done, true)
})
