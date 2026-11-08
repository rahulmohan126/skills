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

### 2. Run the source scan

```bash
python3 <skill-dir>/scripts/scan_source.py <repo-path> > <scratch>/source.json
```

It detects the framework, backend (Supabase / Firebase / Prisma / Drizzle / raw SQL / Mongo), auth library, and collects raw signals: secret-looking strings in tracked files, env files in git, secrets in git history, source map config, `lang` attribute, favicon/robots/sitemap/llms.txt presence, `dangerouslySetInnerHTML`, `set:html`, string-built SQL, security header config, etc. Each finding has a file and line.

Treat the script's output as **leads, not verdicts**. Grep hits produce false positives (a `sk_test_` in a README example, a `service_role` mention in a comment). Open the file and confirm before marking anything FAIL. Equally, the script can't see everything — e.g. it can't tell whether every server action checks the session. For checks that need judgment (S6–S8, S14–S17), read the actual route handlers / server actions / API routes.

### 3. Probe the live site (if there's a URL)

```bash
python3 <skill-dir>/scripts/probe_live.py <url> --max-pages 15 > <scratch>/live.json
```

Uses only the Python stdlib. It fetches the homepage plus pages discovered from the sitemap and internal links, and reports per-page title/description/OG/canonical/H1s/headings/lang/JSON-LD/alt text/noindex/landmarks/word count, plus site-wide: response headers, HTTP→HTTPS and www/apex redirects, robots.txt (and whether AI crawlers are blocked), sitemap.xml, llms.txt, favicon, a random-path request to detect soft 404s, JS bundle sizes, and whether `.map` files are publicly served.

**No URL?** Try to build and serve locally so the runtime checks still get verified:
- Next.js: `npm run build && npm run start` (port 3000)
- Astro: `npm run build && npm run preview` (port 4321)
- Vite: `npm run build && npm run preview` (port 4173)

Run the server in the background, probe `http://localhost:<port>`, then stop it. If the build fails, that is itself a launch blocker — report it. Local probing can't verify L1, L25 (headers are often set by the host), or L32; mark those NOT VERIFIED unless the config in the repo settles it.

**Console errors (L19)** need a real browser. In order of preference: the `claude-in-chrome` skill if available; `npx -y playwright` if the user is OK installing it; otherwise mark NOT VERIFIED and tell the user how to check (open DevTools on the main pages).

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

Severity guides ordering. **Blockers** are anything that leaks secrets or data or lets users act as each other (S1–S8, S13, L24 accidental noindex, L2 empty view-source on a marketing site). Fix these before launch. Everything else is "should fix" or "nice to have" — use the severity tags in the reference files.

### 5. Write the report

Save it as `PROD_READINESS.md` in the repo root (or wherever the user asks), and give a short summary in chat. Structure:

```markdown
# Production readiness — <project name>
<date> · <framework> · <backend> · URL probed: <url or "none (source only)">

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

## Suggested fixes
<Numbered, grouped by effort; framework-specific code where useful.>
```

Evidence must be concrete: `src/lib/supabase.ts:4 uses SUPABASE_SERVICE_ROLE_KEY in a "use client" file` beats "service key may be exposed". Never paste a full secret into the report — show the first 4 characters and the location.

### 6. Offer fixes

After the report, list the fixes you can make and ask before touching files. Group them so the user can say yes to a batch: e.g. "Mechanical fixes I can apply now: add `lang` to the root layout, add `metadataBase` + default OG image, generate `sitemap.xml` and `robots.txt` via `app/sitemap.ts` / `app/robots.ts`, disable production browser source maps. Want me to do those?" Security fixes that change behavior (auth checks, RLS policies, rate limiting) deserve a separate, explicit confirmation with the plan spelled out.

Some fixes aren't code: rotating a leaked key, purging git history, enabling RLS in the Supabase dashboard, setting a custom domain. Explain these as steps for the user — rotating a leaked key comes **before** scrubbing history, because history scrubbing doesn't help if the key was already pushed to a remote.

## Framework notes

Most checks behave differently per framework. The reference files carry the per-check details; the high-level shape is:

- **Next.js (App Router)**: metadata via `export const metadata` / `generateMetadata`, `app/sitemap.ts`, `app/robots.ts`, `app/icon.*`, headers in `next.config.*` `headers()` or middleware. Server Components/Actions run on the server, but every Server Action is a public POST endpoint — it must authorize itself. `NEXT_PUBLIC_*` vars ship to the browser.
- **Next.js (Pages Router)**: `next/head`, `_document` for `lang`, `pages/api/*` for routes, `getServerSideProps`.
- **Astro**: mostly static HTML by default (good for L2). `<head>` in layouts, `@astrojs/sitemap`, `public/robots.txt`, `PUBLIC_*` vars ship to browser, `set:html` is the XSS foot-gun. Islands (`client:*`) are where client JS comes from.
- **Vite / CRA SPA**: the usual failures cluster here — empty view-source (L2), "Vite + React" title (L4), single `index.html` title for every route (L5), no real 404 (L3). `VITE_*` / `REACT_APP_*` vars ship to the browser. If it's a marketing/content site, recommend prerendering or migrating to Astro/Next; if it's an app behind login, L2/L5/L8 matter much less — say so (WARN or N/A rather than FAIL for pages that are behind auth).

Calibrate to what the site *is*. A logged-in dashboard doesn't need structured data or llms.txt on its inner pages; a marketing site does. Judge public, indexable pages by the SEO checklist and authenticated pages mainly by the security checklist.
