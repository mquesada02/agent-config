import { test, mock } from 'node:test'
import assert from 'node:assert/strict'
import { total, fetchRate } from '../src/price.js'

test('runs total', () => {
  total([1, 2])
})

test('uses the rate source', () => {
  const source = mock.fn(() => 5)
  const result = fetchRate(source)
  assert.equal(result, 5)
})

test('adds items', (t) => {
  t.plan(1)
  t.assert.equal(total([1, 2]), 3)
})
