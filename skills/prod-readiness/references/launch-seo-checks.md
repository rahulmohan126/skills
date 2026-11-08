# Launch & SEO checks (L1–L32)

Severity tags: **[blocker]** fix before launch · **[high]** should fix before launch · **[med]** fix soon · **[low]** polish.

`probe_live.py` field names are given as `live.<field>`; `scan_source.py` as `src.<field>`.

## Contents
- Identity & first impression: L1–L4
- Page metadata: L5–L8, L11, L21, L22, L24
- Headings & content structure: L9, L10, L23, L27, L28
- Crawl & discovery: L12–L15, L30
- Accessibility basics: L16, L17, L29
- Build & runtime hygiene: L18–L20, L26
- Trust & transport: L25, L31, L32

---

### L1 Platform hostname in URL — [high]
The production site is served from a custom domain, not `*.vercel.app`, `*.netlify.app`, `*.pages.dev`, `*.onrender.com`, `*.herokuapp.com`, `*.github.io`, `*.fly.dev`, `*.railway.app`, `*.web.app`, `*.firebaseapp.com`, `*.amplifyapp.com`, `*.surge.sh`.
- Live: `live.platform_hostname` (checks both the probed origin and the site host the build emits). Also check canonical URLs, OG `og:url`, sitemap `<loc>`s — they often point at the platform hostname even when a custom domain exists.
- Source: grep for those hostnames in `site`/`metadataBase`/`NEXT_PUBLIC_SITE_URL`/`astro.config` `site:`.
- Preview URLs are fine on platform hostnames; only the production URL and any URLs the site *emits* (canonical, sitemap, OG) matter.
- If the platform URL is still reachable alongside the custom domain, it should redirect or carry a canonical pointing to the custom domain.

### L2 View-source empty — [blocker for public content sites; N/A for auth-only apps]
`curl` of a public page returns real content (headings, paragraphs), not just `<div id="root"></div>` + scripts. Crawlers and link previews often don't run JS.
- Live: `live.pages[].text_chars` / `word_count` from the raw HTML (scripts stripped — what a non-JS crawler reads) and `live.pages[].empty_shell`. FAIL if a public page has < ~300 characters of server-rendered text.
- Watch for content that only appears after hydration even on SSR frameworks: menus rendered through portals (Radix/Headless UI `Portal` returns nothing until a client effect runs, `forceMount` doesn't change that), tabs/accordions that mount panels on open, `client:only` islands.
- Source: Vite/CRA SPA with no prerender plugin → almost certainly FAIL. Next.js pages marked `"use client"` at the top of the page that fetch everything in `useEffect` → likely FAIL for those pages. Astro → usually PASS unless content is in `client:only` islands.
- Fix: SSR/SSG (Next/Astro), or prerender (`vite-plugin-prerender`, `react-snap`) for SPAs.

### L3 No 404 page / soft 404 — [high]
Unknown URLs return HTTP **404** with a helpful custom page (link home, maybe search).
- Live: `live.soft_404` requests a random path at the root **and** a bogus slug inside each section of the sitemap (`/products/not-a-real-slug`). FAIL if any returns 200 (soft 404 — SPA fallback, or a `[slug]` page that renders for unknown slugs), or if the 404 body is a bare platform default (< ~200 chars, no link home).
- Next.js dynamic routes must call `notFound()` in the **page component** for unknown slugs, not only in `generateMetadata` — guarding only metadata produces a 200 page (or a 500) for garbage slugs. Hosts can mask this (Vercel 404s paths outside the prerender manifest), so a route that looks fine in production can still be broken; reproduce locally when in doubt.
- Source: Next `app/not-found.tsx` or `pages/404.tsx`; Astro `src/pages/404.astro`. SPAs on Vercel/Netlify with a catch-all rewrite to `/index.html` produce soft 404s — need a real 404 route plus host config, or accept WARN for app-only SPAs.

### L4 Framework leaked in tab/header — [high]
No default scaffolding left: title "Vite + React", "Create Next App", "Astro Basics", "React App"; default `vite.svg`/`react.svg`/Next/Astro favicon; `X-Powered-By: Next.js` header; `generator` meta from the starter.
- Live: `live.pages[].title`, `live.leaky_headers` (`x-powered-by`, `x-generator`, `x-nextjs-cache`), `live.pages[].meta_generator`, `live.favicon`.
- Source: `src.scaffold_leftovers` (default titles, default svgs in `public/`, `poweredByHeader` not set to false in next.config).
- Fix (Next): `poweredByHeader: false` in next.config.

### L5 Duplicate page titles — [high]
Each indexable page has a unique `<title>`.
- Live: `live.duplicate_titles` across crawled pages.
- Source: SPA with one `index.html` title and no per-route title management → FAIL. Next: pages without their own `metadata`/`generateMetadata` inherit the root title — check `title.template` is used and each page sets a title. Astro: layout prop for title passed per page.

### L6 No meta description — [high]
Every indexable page has `<meta name="description">`.
- Live: `live.pages[].description` missing.
- Quality is judged separately in L22.

### L7 No OpenGraph tags/image — [high]
Pages have `og:title`, `og:description`, `og:image` (absolute URL, ~1200×630, reachable), `og:url`; ideally `twitter:card=summary_large_image`.
- Live: `live.pages[].og`; `live.og_images` fetches each image and reports status/content-type.
- Live: `live.pages_missing_og`, `live.og_images` (each distinct image fetched: absolute?, status, content-type must be `image/*`).
- Common failure: relative `og:image` URL (Next without `metadataBase`; Astro without `site`). That counts as FAIL — scrapers need absolute URLs.
- Next: `app/opengraph-image.(png|tsx)` or `metadata.openGraph.images` + `metadataBase`.

### L8 No structured data — [med]
At least the homepage has JSON-LD (`Organization` or `WebSite`; plus `Article`, `Product`, `BreadcrumbList`, `FAQPage`, `SoftwareApplication` as appropriate). JSON must parse.
- Live: `live.pages[].jsonld_types`, `jsonld_errors` (doesn't parse; top-level node without `@context`; raw `<` inside the block — breaks the script element and is an injection risk, escape as `\u003c`), `jsonld_dangling_ids` (`{"@id": …}` references to nodes not declared on the page → WARN).
- Only describe what's really on the page — no invented ratings, reviews, prices or FAQ entries.
- N/A for pages behind auth.

### L9 Multiple H1s — [med]
Each page has exactly one `<h1>`. (HTML5 allows more, but for SEO and screen-reader clarity one is the norm.)
- Live: `live.pages[].h1_count > 1`. Common cause: logo wrapped in `<h1>` in the header plus a page H1.

### L10 No H1 — [high]
Each page has an `<h1>`. Hero text styled big but in a `<div>`/`<p>` counts as missing.
- Live: `live.pages[].h1_count == 0`.

### L11 No canonical tag — [high]
Each indexable page has `<link rel="canonical">` with an absolute URL on the production domain, pointing to itself (or the preferred duplicate).
- Live: `live.canonical_problems` (missing, relative, other host, points to another path), `live.all_canonicals_same` (every page canonicalizes to one URL — a hardcoded root-layout canonical).
- Next: `alternates: { canonical: './' }` per page with `metadataBase`. Astro: `new URL(Astro.url.pathname, Astro.site)`.

### L12 No `llms.txt` — [low]
`/llms.txt` exists: markdown with site name, one-line summary, and links to key pages/docs. Emerging convention — WARN rather than FAIL if missing.
- Live: `live.llms_txt` — 200, not an HTML fallback, and structured per the convention: `# Site name` H1, a `> one-line summary` blockquote, `## Section` headings with link lists. Missing structure → WARN. Source: `public/llms.txt` or a route.

### L13 AI blocked in `robots.txt` — [med]
`robots.txt` doesn't unintentionally block AI/answer-engine crawlers (`GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `Claude-User`, `Claude-SearchBot`, `anthropic-ai`, `PerplexityBot`, `Google-Extended`, `Applebot-Extended`, `CCBot`) and doesn't `Disallow: /` for `*`.
- Live: `live.robots.blocked_ai_agents`, `live.robots.blocks_all_for_star`, `live.robots.html_fallback` (SPA returning index.html for /robots.txt = no robots.txt). Parsed with crawler semantics: a group naming the agent replaces `*`, longest matching rule wins, `Allow` breaks ties.
- If the block looks deliberate (comment explaining it), report as PASS with a note — it's a business decision. If `User-agent: * / Disallow: /` is on production, that's a **blocker** (usually a staging robots.txt shipped by accident).
- Also: robots.txt should have a `Sitemap:` line (`live.robots.sitemap_lines`); missing → FAIL for this check.

### L14 No favicon — [med]
A favicon is served (`/favicon.ico` or `<link rel="icon">` resolves with 200), ideally plus `apple-touch-icon` (180×180) and it isn't the framework default.
- Live: `live.favicon` — `/favicon.ico` requested directly must return an image (browsers and crawlers ask for it regardless of `<link>`), the `<link rel="icon">` target must resolve, and `apple_touch_icon` / `manifest` missing → WARN. Source: `src.favicon`.

### L15 No `sitemap.xml` — [high]
`/sitemap.xml` (or a sitemap index) exists, is valid XML, lists the public pages with absolute production URLs, and doesn't list noindexed/404 pages.
- Live: `live.sitemap` — status, `url_count`, `hosts`, `duplicates`, `insecure` (http:// locs), `entries_not_200`, `blocked_by_robots` (in the sitemap but disallowed — contradictory, FAIL), plus `live.sitemap_noindexed` (FAIL) and `live.pages_linked_not_in_sitemap` (WARN).
- Next: `app/sitemap.ts` or `next-sitemap`. Astro: `@astrojs/sitemap` (needs `site` in config).

### L16 No lang attribute — [high]
`<html lang="en">` (or appropriate language) on every page.
- Live: `live.pages[].lang`. Source: `src.html_lang` (Next root layout `<html lang>`, Pages Router `_document`, Astro layout, Vite `index.html`).

### L17 Missing alt text — [high]
Every `<img>` has an `alt` attribute; meaningful images have descriptive alt; decorative ones use `alt=""`. Also check `next/image` / Astro `<Image>` usages in source.
- Live: `live.pages[].imgs_no_alt_attr` (FAIL), `live.alt_summary.empty_share` — if more than ~40% of images are `alt=""`, that's FAIL: decorative is being used as a way to skip writing alt text. Source: `src.img_missing_alt`.
- Alt text like "image", "photo", "img_1234.jpg" (`weak_alt`) → WARN. Also WARN when alt text contradicts the file (alt says "vertical illustration" on a landscape image) — that usually means the wrong file is in place; flag it, don't rewrite the alt to match a guess.

### L18 Source maps — [high]
Production JS source maps aren't publicly served (they expose original source, comments, sometimes secrets). Uploading them privately to Sentry etc. is fine.
- Build output (most reliable): `src.build_output.<dir>.map_files` and `files_referencing_sourcemap` — any `.map` in `out/`, `dist/`, `.next/static` or a shipped JS/CSS file with a `sourceMappingURL` comment → FAIL. Only present if a build exists; build first if you can.
- Live: `live.sourcemaps_served` (follows each bundle's `sourceMappingURL` or tries `<bundle>.map`). FAIL if any returns 200 with map JSON.
- Source: `src.sourcemaps` — Next `productionBrowserSourceMaps: true`; Vite `build.sourcemap: true` (use `'hidden'` if uploading to Sentry); CRA without `GENERATE_SOURCEMAP=false`; Astro `vite.build.sourcemap`.

### L19 Console errors — [high]
No errors (and ideally no warnings like hydration mismatches, 404'd assets, CSP violations) in the browser console on main pages.
- Needs a browser — `scripts/browser_check.mjs` (see SKILL.md step 3). FAIL on any console error, uncaught exception, failed request, or 4xx/5xx subresource; WARN on console warnings (hydration mismatch warnings deserve a look — they mean server and client HTML differ). If no browser: NOT VERIFIED, plus list what the static scan suggests (`src.hydration_risk`).
- `live.broken_assets` lists referenced scripts/styles/images that 4xx — those always produce console errors, so that's a FAIL even without a browser.

### L20 Massive JS bundles — [high]
First-load JS on the heaviest page is reasonable. Budget (gzipped first-party `<script src>`, excluding `nomodule`): ≤ 300 KB PASS, 300–500 KB WARN, > 500 KB FAIL. A single chunk > 250 KB gzipped is a red flag on its own.
- Live: `live.js_weight.heaviest_pages`, `largest_chunks_kb_gzip` (measured by gzipping each script at level 9, so it's comparable across hosts; scripts loaded later via dynamic import aren't counted).
- Source: after `npm run build`, Next prints route sizes ("First Load JS"); Vite prints chunk sizes. Look for whole-library imports (`lodash`, `moment`, icon packs imported via barrel, full `@mui/icons-material`), and heavy libs in client components that could be server-only.

### L21 Title length & word order — [med]
Titles are 20–60 characters, lead with the page-specific keyword, and put the brand last: `Pricing — Acme` not `Acme | Home | Pricing`. Homepage can be `Acme — <value prop>`.
- Live: `live.pages[].title_length` (outside 20–60 → FAIL), `live.brand_first_titles` (most titles share the same leading segment → FAIL).

### L22 Description quality — [med]
Descriptions are 70–165 characters (outside → FAIL), unique per page, describe that page specifically (not the same tagline everywhere), no keyword stuffing, and aren't placeholder text ("Generated by create next app", "My Astro site", lorem ipsum).
- Live: `live.pages[].description_length`, `live.duplicate_descriptions`.

### L23 Heading hierarchy sequential — [med]
Headings don't skip levels going down (h1 → h3 without h2). Going back up is fine.
- Live: `live.pages[].heading_skips`, `heading_outline`. Often caused by picking heading tags for font size — fix with CSS classes instead.

### L24 Accidental `noindex` — [blocker]
Production pages that should be indexed don't have `<meta name="robots" content="noindex">` or `X-Robots-Tag: noindex`. Very common after copying staging config, or Vercel preview protection.
- Live: `live.pages[].noindex`, `live.headers['x-robots-tag']`.
- Source: grep `noindex`, `robots: { index: false }` in Next metadata — check whether it's gated on env correctly.
- Intentionally noindexed pages (e.g. /login, /dashboard, thank-you pages) are fine — and they should be absent from the sitemap.

### L25 Security response headers — [high]
Same as S18 — evaluate once, report under S18, and reference it here ("see S18").

### L26 Image delivery — [med]
Images are appropriately sized and in modern formats (WebP/AVIF), lazy-loaded below the fold, with `width`/`height` (or aspect-ratio) to avoid layout shift. Hero/LCP image is *not* lazy-loaded and ideally preloaded/`priority`.
- Live: `live.pages[].images` (format, has dimensions, loading attr), `live.large_images` (HEAD content-length > 300 KB).
- Source: raw `<img>` in Next instead of `next/image`, or in Astro instead of `astro:assets` `<Image>` → WARN. Large files in `public/` → `src.large_public_images`.

### L27 Semantic landmarks — [med]
Pages use `<header>`, `<nav>`, `<main>` (exactly one), `<footer>` rather than div soup. Helps screen readers and content extraction. A "Skip to main content" link targeting `<main id=…>` is a plus, and necessary if the header has many tab stops.
- Live: `live.pages[].landmarks`. FAIL if no `<main>`; WARN if `<nav>` or others are missing.

### L28 Thin content — [med]
Indexable pages have substantive unique text: fewer than ~150 words inside `<main>` → WARN (expected for login/thank-you pages — note it and move on). Placeholder copy ("Lorem ipsum", "Coming soon", "TODO") is a FAIL. Never pad pages to clear this.
- Live: `live.pages[].main_word_count` (falls back to `word_count` when there's no `<main>`), `live.pages[].placeholder_text`.
- Source: grep for lorem ipsum / TODO copy in page components.

### L29 Descriptive link text — [med]
Links say where they go — no "click here", "read more", "learn more", "here" without context; icon-only links have `aria-label`.
- Live: `live.pages[].vague_links`, `live.pages[].empty_links`.

### L30 Internal link graph — [med]
Every important public page is reachable via normal `<a href>` links from the homepage within a few clicks (not only via JS `onClick` navigation or the sitemap). No orphan pages; no internal links to 404s.
- Live: `live.link_graph.zero_inbound` (pages no other crawled page links to → WARN), `min_inbound`, `broken_internal_links` (FAIL), `live.pages[].internal_links`.
- Navigation that only exists after hydration (portalled dropdowns, JS-built menus) is invisible to non-rendering crawlers (GPTBot, ClaudeBot, PerplexityBot) — the links must be in the server HTML. CSS-revealed menus (`:hover`/`:focus-within`, closed panels `visibility: hidden` not `display: none` or unmounted) keep them crawlable.
- Source: `onClick={() => router.push(...)}` on non-link elements for primary navigation → WARN.

### L31 Freshness & authorship — [low]
Content pages (blog, docs, articles) show a real published/updated date and an author; ideally reflected in JSON-LD (`datePublished`, `dateModified`, `author`) and sitemap `<lastmod>`. Footer copyright year is current. N/A for sites with no editorial content.
- Live: `live.pages[].dates_found`, `live.pages[].jsonld_types` (check `Article`/`BlogPosting` nodes for `datePublished`/`dateModified`/`author`), `live.copyright_year`.
- If the content has no real dates, **don't invent them** — a fabricated date misrepresents freshness. Recommend adding genuine dates to the content source; an `author` pointing at the site's `Organization` node can be added honestly right away.

### L32 HTTPS & hostname canonicalization — [high]
`http://` → `https://` with a 301/308; `www` and apex resolve to one canonical host (the other redirects with 301/308); no mixed content.
- Live: `live.redirects.http_to_https.ok`, `live.redirects.alt_host.both_serve_200` (FAIL — two hosts serving the same site), `live.pages[].insecure_urls` (any `http://` URL the page emits: canonical, og:url/og:image, alternates, scripts, images, links), `live.sitemap.insecure`.
- Overlaps S19 — evaluate once, report under S19 and reference it here.
