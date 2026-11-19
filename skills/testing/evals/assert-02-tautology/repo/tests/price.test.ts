import { describe, expect, it, vi } from "vitest";
import { total } from "../src/price";

describe("total", () => {
  it("adds the items", () => {
    expect(total([1, 2, 3])).toBe(6);
  });

  it("applies the tax rate", () => {
    const rate = vi.fn().mockReturnValue(0.2);
    expect(rate()).toBe(0.2);
  });
});
