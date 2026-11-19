import assert from "node:assert/strict";
import { test } from "node:test";
import { total } from "../src/price.js";

test("waits and adds", async () => {
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(total([1, 2, 3]), 6);
});
