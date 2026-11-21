const { render } = require('../src/render')

test('renders', () => {
  expect(render(new Date())).toMatchSnapshot()
})
