const { total } = require('../src/price')

test('adds', () => {
  expect(total([1, 2])).toBe(3)
})
