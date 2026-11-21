import { expect, test } from 'vitest'

test('sometimes passes', { retry: 3 }, () => {
  expect(Math.round(1.4)).toBe(1)
})
