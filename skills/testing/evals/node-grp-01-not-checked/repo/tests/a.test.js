import { test } from 'node:test'
import assert from 'node:assert/strict'
import { a } from '../src/a.js'

test('reads a', () => {
  assert.equal(a, 1)
})
