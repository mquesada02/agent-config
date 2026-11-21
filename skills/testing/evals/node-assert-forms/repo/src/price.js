export function total(items) {
  return items.reduce((a, b) => a + b, 0)
}
export function fetchRate(source) {
  return source()
}
