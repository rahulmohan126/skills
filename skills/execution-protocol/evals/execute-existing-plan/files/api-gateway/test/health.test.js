import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "../src/server.js";

test("health returns ok", async () => {
  const server = createServer().listen(0);
  const { port } = server.address();
  const res = await fetch(`http://127.0.0.1:${port}/health`);
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true });
  server.close();
});
