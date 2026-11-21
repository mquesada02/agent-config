import { expect, test } from 'vitest'
import { total } from '../src/price'

test('adds', () => {
  expect(total([1, 2])).toBe(3)
})
