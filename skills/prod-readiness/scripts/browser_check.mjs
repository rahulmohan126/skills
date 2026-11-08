#!/usr/bin/env node
// Load pages in headless Chrome and report console errors/warnings, uncaught
// exceptions, failed requests and 4xx/5xx responses (check L19). Prints JSON.
//
//   node browser_check.mjs <origin> [path ...] [--pw-dir DIR]
//
// Needs `playwright-core` (no browser download; it drives the Chrome already
// installed). Resolved from, in order: --pw-dir, the current directory's
// node_modules. To get it without touching the audited repo:
//   npm i --prefix <scratch>/pw playwright-core
//   node browser_check.mjs https://example.com / /pricing --pw-dir <scratch>/pw
// If no system Chrome exists, `npx playwright-core install chromium` fetches one.

import { createRequire } from "node:module";
import { join, resolve } from "node:path";

const args = process.argv.slice(2);
const pwIdx = args.indexOf("--pw-dir");
const pwDir = pwIdx >= 0 ? resolve(args.splice(pwIdx, 2)[1]) : process.cwd();
const [origin, ...rest] = args;
if (!origin) {
  console.error("usage: browser_check.mjs <origin> [path ...] [--pw-dir DIR]");
  process.exit(2);
}
const paths = rest.length ? rest : ["/"];

let chromium;
try {
  ({ chromium } = createRequire(join(pwDir, "package.json"))("playwright-core"));
} catch {
  console.log(JSON.stringify({ status: "not_evaluated", reason: `playwright-core not found from ${pwDir}` }));
  process.exit(0);
}

let browser;
for (const opts of [{ channel: "chrome" }, { channel: "msedge" }, {}]) {
  try {
    browser = await chromium.launch(opts);
    break;
  } catch {}
}
if (!browser) {
  console.log(JSON.stringify({ status: "not_evaluated", reason: "no Chrome/Edge/Playwright Chromium to launch" }));
  process.exit(0);
}

const results = [];
try {
  for (const path of paths) {
    const url = new URL(path, origin).href;
    const r = { path, errors: [], warnings: [], uncaught: [], failed_requests: [], bad_responses: [] };
    const page = await browser.newPage();
    page.on("console", (m) => {
      const t = m.text().slice(0, 240);
      if (m.type() === "error") r.errors.push(t);
      else if (m.type() === "warning") r.warnings.push(t);
    });
    page.on("pageerror", (e) => r.uncaught.push(e.message.slice(0, 240)));
    page.on("requestfailed", (req) => {
      const why = req.failure()?.errorText ?? "";
      // Media/fetch aborted when scrolled away or superseded is not a defect.
      if (why === "net::ERR_ABORTED" && ["media", "fetch", "image"].includes(req.resourceType())) return;
      r.failed_requests.push(`${req.url().slice(0, 160)} (${why})`);
    });
    page.on("response", (res) => {
      if (res.status() >= 400 && res.url() !== url) r.bad_responses.push(`${res.status()} ${res.url().slice(0, 160)}`);
    });
    try {
      const res = await page.goto(url, { waitUntil: "load", timeout: 30_000 });
      r.status = res?.status();
      // Scroll to trigger lazy-loaded images, islands and client components.
      for (let i = 0; i < 6; i++) {
        await page.mouse.wheel(0, 4000);
        await page.waitForTimeout(250);
      }
      await page.waitForTimeout(1000);
    } catch (e) {
      r.uncaught.push(`navigation: ${e.message.slice(0, 200)}`);
    }
    await page.close();
    results.push(r);
  }
} finally {
  await browser.close();
}

const total = (k) => results.reduce((n, r) => n + r[k].length, 0);
console.log(
  JSON.stringify(
    {
      status: total("errors") + total("uncaught") + total("failed_requests") + total("bad_responses") ? "fail" : total("warnings") ? "warn" : "pass",
      pages: results.length,
      counts: { errors: total("errors"), warnings: total("warnings"), uncaught: total("uncaught"), failed_requests: total("failed_requests"), bad_responses: total("bad_responses") },
      results,
    },
    null,
    1,
  ),
);
