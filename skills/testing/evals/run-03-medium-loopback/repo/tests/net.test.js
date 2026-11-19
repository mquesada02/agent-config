import assert from "node:assert/strict";
import net from "node:net";
import { test } from "node:test";

test("a closed loopback port refuses the connection", async () => {
  const socket = net.connect(9, "127.0.0.1");
  const error = await new Promise((resolve) => socket.once("error", resolve));
  assert.equal(error.code, "ECONNREFUSED");
});
