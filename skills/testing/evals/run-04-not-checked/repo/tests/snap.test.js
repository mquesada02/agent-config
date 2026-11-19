import { test } from "node:test";

test("matches the snapshot", (t) => {
  t.assert.snapshot({ total: 6 });
});
