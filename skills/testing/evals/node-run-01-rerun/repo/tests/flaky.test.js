import { test } from 'node:test'
import assert from 'node:assert/strict'

test('sometimes passes', () => {
  assert.equal(Math.round(1.4), 1)
})
