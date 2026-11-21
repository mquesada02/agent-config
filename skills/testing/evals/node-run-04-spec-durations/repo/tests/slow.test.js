import { test } from 'node:test'
import assert from 'node:assert/strict'

test('takes two seconds', async () => {
  await new Promise((resolve) => setTimeout(resolve, 2000))
  assert.equal(1, 1)
})
