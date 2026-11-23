import { format } from "./format-money.js";

/** Sums the prices and formats the sum. */
export function total(prices) {
  return format(prices.reduce((a, b) => a + b, 0));
}
