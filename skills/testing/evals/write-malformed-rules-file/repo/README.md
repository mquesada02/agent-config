# Fixture

`clamp(value, min, max)` in `src/clamp.js` limits a number to a range.

- A value above the maximum gives the maximum: `clamp(5, 0, 3)` returns `3`.
- A value below the minimum gives the minimum: `clamp(-2, 0, 3)` returns `0`.
- A value inside the range stays: `clamp(2, 0, 3)` returns `2`.
