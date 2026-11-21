test('waits on the real clock', async () => {
  await new Promise((resolve) => setTimeout(resolve, 500))
  expect(1).toBe(1)
})

test('waits on a fake clock', async () => {
  jest.useFakeTimers()
  let done = false
  setTimeout(() => { done = true }, 500)
  await jest.advanceTimersByTimeAsync(500)
  jest.useRealTimers()
  expect(done).toBe(true)
})
