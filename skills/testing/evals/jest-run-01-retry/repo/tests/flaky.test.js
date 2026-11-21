jest.retryTimes(2)

test('sometimes passes', () => {
  expect(Math.round(1.4)).toBe(1)
})
