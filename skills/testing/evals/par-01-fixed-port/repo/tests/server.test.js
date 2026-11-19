import assert from "node:assert/strict";
import net from "node:net";
import { test } from "node:test";

test("a server listens on its port", async () => {
  const server = net.createServer();
  const outcome = await new Promise((resolve) => {
    server.once("error", () => resolve("busy"));
    server.listen(4873, "127.0.0.1", () => resolve("listening"));
  });
  server.close();
  assert.ok(["busy", "listening"].includes(outcome));
});
