import { test } from 'node:test'
import assert from 'node:assert/strict'
import { total } from '../src/price.js'

test('adds', () => {
  assert.equal(total([1, 2]), 3)
})
