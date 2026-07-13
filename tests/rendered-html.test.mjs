import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the authenticated Defendly shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Defendly — AI Interview Preparation<\/title>/i);
  assert.match(html, /Preparing your interview room/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("contains authentication, adaptive scoring, providers, and real-time practice", async () => {
  const [page, layout, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /api\/auth\/session/);
  assert.match(page, /api\/cvs\/extract/);
  assert.match(page, /api\/evaluations/);
  assert.match(page, /ws\/interview/);
  assert.match(page, /Concept coverage/);
  assert.match(page, /Live interview room/);
  assert.match(page, /Claims under pressure/);
  assert.match(layout, /Defendly/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
});
