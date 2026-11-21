import { test, describe, afterEach } from 'node:test'
import assert from 'node:assert/strict'

test('sets a mode', () => {
  process.env.MODE = 'fast'
  assert.equal(process.env.MODE, 'fast')
})

describe('restores a mode', () => {
  const saved = { ...process.env }
  afterEach(() => {
    process.env = { ...saved }
  })

  test('uses a mode', () => {
    process.env.MODE = 'slow'
    assert.equal(process.env.MODE, 'slow')
  })
})
