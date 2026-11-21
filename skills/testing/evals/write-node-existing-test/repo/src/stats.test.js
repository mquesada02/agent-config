import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sum } from './stats.js'

test('sums', () => {
  assert.equal(sum([1, 2]), 3)
})
