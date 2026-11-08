---
name: prod-readiness
description: Audit a React web app (Next.js, Astro, Vite/CRA, Remix) for production readiness across ~50 launch, SEO, and security checks — leaked API keys and git secrets, Supabase/Firebase RLS and public keys, server-side auth, input validation, security headers, HTTPS, plus titles, meta descriptions, OpenGraph, canonical, H1s, sitemap, robots.txt/AI crawlers, llms.txt, favicon, lang, alt text, source maps, bundle size, soft 404s, console errors, and platform hostnames like vercel.app. Produces a pass/fail report and offers fixes. Use this whenever the user asks if their site/app is "ready to ship", "ready for launch", "production ready", wants a pre-launch / go-live checklist, an SEO or security audit of a React/Next/Astro repo or deployed URL, or says things like "before I launch", "sanity check my site", "what am I missing before deploying" — even if they only mention one area (e.g. just SEO or just security).
---

# Production readiness check

You're auditing a React-family web app before it goes live. The goal is a trustworthy pass/fail verdict per check, with evidence, so the user can fix what matters and ship. A wrong "PASS" is worse than an honest "NOT VERIFIED" — the user is going to rely on this report to decide whether it's safe to launch.

There are two checklists:
- `references/launch-seo-checks.md` — 32 checks (L1–L32): discoverability, polish, and things that make a site look unfinished.
- `references/security-checks.md` — 20 checks (S1–S20): secrets, data access, auth, input handling, transport.

Read both reference files before writing the report; they define what PASS means for each check and how to verify it per framework.

## Workflow

### 1. Get oriented

Figure out:
- **Repo path** (usually the current directory).
- **Live URL**, if any. Ask once if not provided: "Is there a deployed or preview URL I should probe? If not, I can try building and serving locally." A production URL is best; a preview URL is fine but note that platform hostnames on previews are expected (L1 only fails for the *production* URL).
- **Scope**: if the user asked only for SEO or only for security, run just that checklist and say so in the report.
- **A previous report**: if `PROD_READINESS.md` (or a similar audit doc) already exists, read it first. Keep the same check IDs, and in the new report call out what changed since last time — especially **regressions** (was PASS, now FAIL). Regressions are the most useful thing a re-run can tell someone.

### 2. Run the source scan

```bash
python3 <skill-dir>/scripts/scan_source.py <repo-path> > <scratch>/source.json
```

It detects the framework, backend (Supabase / Firebase / Prisma / Drizzle / raw SQL / Mongo), auth library, and collects raw signals: secret-looking strings in tracked files, env files in git, secrets in git history, source map config, `lang` attribute, favicon/robots/sitemap/llms.txt presence, `dangerouslySetInnerHTML`, `set:html`, string-built SQL, security header config, etc. Each finding has a file and line.

Treat the script's output as **leads, not verdicts**. Grep hits produce false positives (a `sk_test_` in a README example, a `service_role` mention in a comment). Open the file and confirm before marking anything FAIL. Equally, the script can't see everything — e.g. it can't tell whether every server action checks the session. For checks that need judgment (S6–S8, S14–S17), read the actual route handlers / server actions / API routes. Source findings and live findings can disagree (e.g. `html_lang` is empty because `<html>` is rendered inside a shared shell component) — when they do, the rendered HTML wins for SEO checks.

The scan also reports `git_state` (HEAD, uncommitted files, commits ahead of upstream). If there's unpushed or uncommitted work, the deployed site is **not** the code you're reading: say so at the top of the report, and be explicit about which checks were verified against what (local build vs. production).

### 3. Probe the rendered site

Most SEO checks are about the HTML a crawler receives, so they need a running site or a build. `probe_live.py` (Python stdlib only) crawls every sitemap URL plus internal links (default cap 60 pages) and reports per-page title/description/OG/canonical/headings/lang/JSON-LD/alt/noindex/landmarks/word counts, and site-wide: security headers, redirects, robots.txt (parsed with real longest-match rules), sitemap health, llms.txt structure, favicon/manifest, soft 404s at the root **and inside each sitemap section** (`/products/not-a-real-slug` — dynamic routes are where soft 404s hide), per-page gzipped JS weight, served source maps, secrets in bundles, broken assets, and the internal link graph.

Pick the target in this order:

1. **Deployed production URL** — `probe_live.py https://example.com`. The only way to verify L1, L32 and the headers the host really sends.
2. **A static build folder** — Astro `dist/` (static output), Next `output: "export"` → `out/`, Vite `dist/`:
   `probe_live.py --serve-dir <repo>/dist`. This serves the folder like a static host (clean URLs, `404.html` with a real 404 status, headers from a `_headers` file if present), with no npm server needed.
3. **A local server** — build, start in the background, probe `http://localhost:<port>`, then stop it:
   - Next.js (server): `npm run build && npm run start` (3000). If `scan_source` reports `next_output_mode: standalone`, `next start` won't serve — copy assets and run the standalone server: `cp -r public .next/standalone/ && mkdir -p .next/standalone/.next && cp -r .next/static .next/standalone/.next/ && PORT=3000 node .next/standalone/server.js`.
   - Astro with a server adapter / Vite SPA: `npm run build && npm run preview` (4321 / 4173).

Check the port is free before starting a server, and stop it afterwards: a stale server from an earlier build serves old HTML and produces findings that look real but aren't. If the build fails, that is itself a launch blocker — report it.

When probing a local origin, the site's own URLs (canonical, sitemap, og:image) name the production domain. The script detects that host and maps those URLs onto the local origin, so the crawl still works; pass `--site-host example.com` if detection picks the wrong one. Locally, L1, L32 and host-set headers can only be judged from config (`_headers`, `vercel.json`, `next.config` `headers()`) — say that's what you did.

The script is a fast net, not an oracle. Spot-check what matters by hand — e.g. curl a couple of real dynamic routes with a bogus slug, and view-source a key page — before calling a check PASS.

**Console errors (L19)** need a real browser. `scripts/browser_check.mjs` drives the Chrome already installed via `playwright-core` (no browser download) and reports console errors/warnings, uncaught exceptions, failed requests and 4xx/5xx responses, scrolling each page to trigger lazy loading:

```bash
npm i --prefix <scratch>/pw playwright-core        # outside the audited repo
node <skill-dir>/scripts/browser_check.mjs <origin> / /pricing /blog/some-post --pw-dir <scratch>/pw
```

Use a handful of representative routes (home, one of each page type). Alternatives: the `claude-in-chrome` skill if available. If nothing can launch a browser, mark L19 NOT VERIFIED with the exact command for the user to run.

### 4. Decide each check

For each check assign exactly one status:

| Status | Meaning |
|---|---|
| ✅ PASS | Verified with evidence |
| ❌ FAIL | Verified problem — will hurt users, SEO, or security |
| ⚠️ WARN | Works but suboptimal, or a judgment call (e.g. title slightly long) |
| ❔ NOT VERIFIED | Couldn't check (no URL, needs browser, needs DB access) — say what's needed |
| ➖ N/A | Doesn't apply (e.g. S10 hash passwords when auth is fully delegated to Clerk/Auth0/Supabase Auth; S16 when there are no uploads) |

Use N/A honestly — it's correct and helpful to say "no user-uploaded files exist, S16 N/A" rather than forcing a PASS. But don't use N/A to dodge a check that's hard to verify.

When a page legitimately fails a check by design (an intentionally noindexed `/portal`, a framework error boundary with no URL), exclude it and say why in a note under the table rather than silently dropping it or failing the check.

Severity guides ordering. **Blockers** are anything that leaks secrets or data or lets users act as each other (S1–S8, S13, L24 accidental noindex, L2 empty view-source on a marketing site). Fix these before launch. Everything else is "should fix" or "nice to have" — use the severity tags in the reference files.

### 5. Write the report

Save it as `PROD_READINESS.md` in the repo root (or wherever the user asks), and give a short summary in chat. Structure:

```markdown
# Production readiness — <project name>
<date> · <framework> · <backend> · commit <sha> (+ uncommitted?) · probed: <prod URL | local build | source only>

> <Deploy-state note if relevant: "3 commits are unpushed — production doesn't have them yet; checks X, Y verified locally only.">

## Verdict
<One line: "Not ready — 3 blockers" / "Ready with minor fixes" / "Ready">
Blockers: N · Fail: N · Warn: N · Pass: N · Not verified: N · N/A: N

## Blockers
<Only blocker-severity FAILs. For each: ID, name, evidence (file:line or URL + what was seen), the fix.>

## Security (S1–S20)
| # | Check | Status | Evidence / notes |
|---|---|---|---|
...

## Launch & SEO (L1–L32)
| # | Check | Status | Evidence / notes |
...

## Not verified — how to close the gaps
<What the user would need to provide or run.>

## Changes since last run
<Only if a previous report existed: regressions first, then newly fixed.>

## Suggested order
| | Item | Effort |
|---|---|---|
<Blockers first, then by value/effort: trivial · moderate · needs a decision. Framework-specific fix details below the table.>

## Fragile passes
<Optional. Things that pass now but would silently regress from an innocent-looking change — e.g. "nav links are in the HTML only because menus are CSS-revealed, not portalled", "titles are length-checked at build time in src/lib/seo.ts". Skip this section if there's nothing non-obvious.>
```

Evidence must be concrete: `src/lib/supabase.ts:4 uses SUPABASE_SERVICE_ROLE_KEY in a "use client" file` beats "service key may be exposed". Never paste a full secret into the report — show the first 4 characters and the location.

### 6. Offer fixes

After the report, list the fixes you can make and ask before touching files. Group them so the user can say yes to a batch: e.g. "Mechanical fixes I can apply now: add `lang` to the root layout, add `metadataBase` + default OG image, generate `sitemap.xml` and `robots.txt` via `app/sitemap.ts` / `app/robots.ts`, disable production browser source maps. Want me to do those?" Security fixes that change behavior (auth checks, RLS policies, rate limiting) deserve a separate, explicit confirmation with the plan spelled out.

Never make a check pass by inventing content: no fabricated publish dates for L31, no alt text that describes what you *guess* is in an image, no made-up ratings or reviews in structured data, no filler words to beat thin-content. That misrepresents the site to crawlers and users. Where the real fix needs information only the user has, say what's needed and leave the check as it is.

Some fixes aren't code: rotating a leaked key, purging git history, enabling RLS in the Supabase dashboard, setting a custom domain. Explain these as steps for the user — rotating a leaked key comes **before** scrubbing history, because history scrubbing doesn't help if the key was already pushed to a remote.

## Framework notes

Most checks behave differently per framework. The reference files carry the per-check details; the high-level shape is:

- **Next.js (App Router)**: metadata via `export const metadata` / `generateMetadata`, `app/sitemap.ts`, `app/robots.ts`, `app/icon.*`, headers in `next.config.*` `headers()` or middleware. Server Components/Actions run on the server, but every Server Action is a public POST endpoint — it must authorize itself. `NEXT_PUBLIC_*` vars ship to the browser.
- **Next.js (Pages Router)**: `next/head`, `_document` for `lang`, `pages/api/*` for routes, `getServerSideProps`.
- **Astro**: mostly static HTML by default (good for L2). `<head>` in layouts, `@astrojs/sitemap`, `public/robots.txt`, `PUBLIC_*` vars ship to browser, `set:html` is the XSS foot-gun. Islands (`client:*`) are where client JS comes from.
- **Vite / CRA SPA**: the usual failures cluster here — empty view-source (L2), "Vite + React" title (L4), single `index.html` title for every route (L5), no real 404 (L3). `VITE_*` / `REACT_APP_*` vars ship to the browser. If it's a marketing/content site, recommend prerendering or migrating to Astro/Next; if it's an app behind login, L2/L5/L8 matter much less — say so (WARN or N/A rather than FAIL for pages that are behind auth).

Calibrate to what the site *is*. A logged-in dashboard doesn't need structured data or llms.txt on its inner pages; a marketing site does. Judge public, indexable pages by the SEO checklist and authenticated pages mainly by the security checklist.
