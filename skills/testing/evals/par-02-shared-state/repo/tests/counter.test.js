import assert from "node:assert/strict";
import { test } from "node:test";

let counter = 0;

test("the first test counts once", () => {
  counter += 1;
  assert.equal(counter, 1);
});

test("the second test counts twice", () => {
  counter += 1;
  assert.equal(counter, 2);
});
