import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

test("writes and reads a file", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "fixture-"));
  const file = path.join(dir, "note.txt");
  fs.writeFileSync(file, "hello");
  assert.equal(fs.readFileSync(file, "utf8"), "hello");
  fs.rmSync(dir, { recursive: true });
});
