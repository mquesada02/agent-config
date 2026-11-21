import { expect, test } from 'vitest'
import { sum } from './stats'

test('sums', () => {
  expect(sum([1, 2])).toBe(3)
})
