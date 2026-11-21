test('sets a mode', () => {
  process.env.MODE = 'fast'
  expect(process.env.MODE).toBe('fast')
})

describe('restores a mode', () => {
  const saved = { ...process.env }
  afterEach(() => {
    process.env = { ...saved }
  })

  test('uses a mode', () => {
    process.env.MODE = 'slow'
    expect(process.env.MODE).toBe('slow')
  })
})
