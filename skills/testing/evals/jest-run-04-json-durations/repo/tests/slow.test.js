test('takes two seconds', async () => {
  await new Promise((resolve) => setTimeout(resolve, 2000))
  expect(1).toBe(1)
})
