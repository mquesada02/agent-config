import assert from "node:assert/strict";
import { test } from "node:test";
import { total } from "../../src/price.js";

test("adds the items", () => {
  assert.equal(total([1, 2, 3]), 6);
});
