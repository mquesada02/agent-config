export function total(items: number[]): number {
  return items.reduce((a, b) => a + b, 0)
}
export function fetchRate(source: () => number): number {
  return source()
}
