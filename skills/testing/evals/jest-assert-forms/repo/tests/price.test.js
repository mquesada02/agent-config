const { total, fetchRate } = require('../src/price')

test('runs total', () => {
  total([1, 2])
})

test('uses the rate source', () => {
  const source = jest.fn().mockReturnValue(5)
  const result = fetchRate(source)
  expect(result).toBe(5)
})

test('adds items', () => {
  expect.assertions(1)
  expect(total([1, 2])).toBe(3)
})
