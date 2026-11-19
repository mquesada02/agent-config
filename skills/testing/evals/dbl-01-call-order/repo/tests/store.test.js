import assert from "node:assert/strict";
import { mock, test } from "node:test";

function saveAll(store, items) {
  for (const item of items) {
    store.put(item);
  }
}

test("saves the items in order", () => {
  const store = { put: mock.fn() };
  saveAll(store, ["a", "b"]);
  assert.equal(store.put.mock.callCount(), 2);
  assert.deepEqual(store.put.mock.calls[0].arguments, ["a"]);
  assert.deepEqual(store.put.mock.calls[1].arguments, ["b"]);
});
