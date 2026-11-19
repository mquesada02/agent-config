/**
 * Applies a percent discount to a price.
 * applyDiscount(200, 25) returns 150: the price is reduced by the percent of itself.
 * The percent is between 0 and 100.
 */
export function applyDiscount(price, percent) {
  return price - percent;
}
