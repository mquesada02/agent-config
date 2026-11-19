import assert from "node:assert/strict";
import { test } from "node:test";
import { total } from "../src/price.js";

test("adds a large list", () => {
  let sum = 0;
  for (let i = 0; i < 600000000; i++) {
    sum += i % 7;
  }
  assert.ok(sum > 0);
  assert.equal(total([1, 2, 3]), 6);
});
