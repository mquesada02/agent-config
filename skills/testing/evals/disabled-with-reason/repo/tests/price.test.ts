import { describe, expect, it } from "vitest";
import { total } from "../src/price";

describe("total", () => {
  it("adds the items", () => {
    expect(total([1, 2, 3])).toBe(6);
  });

  it("handles an empty list", () => {
    total([]);
  });
});
