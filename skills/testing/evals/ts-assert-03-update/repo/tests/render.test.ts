import { expect, test } from 'vitest'
import { render } from '../src/render'

test('renders', () => {
  expect(render(new Date())).toMatchSnapshot()
})
