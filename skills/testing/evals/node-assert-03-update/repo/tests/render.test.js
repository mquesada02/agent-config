import { test } from 'node:test'
import { render } from '../src/render.js'

test('renders', (t) => {
  t.assert.snapshot(render(new Date()))
})
