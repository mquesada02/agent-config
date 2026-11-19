import assert from "node:assert/strict";
import { test } from "node:test";
import { total } from "../../src/price.js";

test("adds nothing", () => {
  assert.equal(total([]), 0);
});
