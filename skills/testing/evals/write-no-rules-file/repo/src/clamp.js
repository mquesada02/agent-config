/**
 * Limits a number to a range.
 * clamp(5, 0, 3) returns 3. clamp(-2, 0, 3) returns 0. clamp(2, 0, 3) returns 2.
 */
export function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}
