import { expect, test } from 'vitest'
import { a } from '../src/a'

test('reads a', () => {
  expect(a).toBe(1)
})
