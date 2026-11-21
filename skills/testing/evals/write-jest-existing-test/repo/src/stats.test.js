const { sum } = require('./stats')

test('sums', () => {
  expect(sum([1, 2])).toBe(3)
})
