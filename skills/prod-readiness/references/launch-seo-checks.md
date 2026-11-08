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
- Live: `live.platform_hostname`. Also check canonical URLs, OG `og:url`, sitemap `<loc>`s — they often point at the platform hostname even when a custom domain exists.
- Source: grep for those hostnames in `site`/`metadataBase`/`NEXT_PUBLIC_SITE_URL`/`astro.config` `site:`.
- Preview URLs are fine on platform hostnames; only the production URL and any URLs the site *emits* (canonical, sitemap, OG) matter.
- If the platform URL is still reachable alongside the custom domain, it should redirect or carry a canonical pointing to the custom domain.

### L2 View-source empty — [blocker for public content sites; N/A for auth-only apps]
`curl` of a public page returns real content (headings, paragraphs), not just `<div id="root"></div>` + scripts. Crawlers and link previews often don't run JS.
- Live: `live.pages[].word_count` from the raw HTML and `live.pages[].empty_shell`. FAIL if public pages have < ~50 words of server-rendered text.
- Source: Vite/CRA SPA with no prerender plugin → almost certainly FAIL. Next.js pages marked `"use client"` at the top of the page that fetch everything in `useEffect` → likely FAIL for those pages. Astro → usually PASS unless content is in `client:only` islands.
- Fix: SSR/SSG (Next/Astro), or prerender (`vite-plugin-prerender`, `react-snap`) for SPAs.

### L3 No 404 page / soft 404 — [high]
Unknown URLs return HTTP **404** with a helpful custom page (link home, maybe search).
- Live: `live.soft_404` requests a random path. FAIL if status is 200 (soft 404 — SPA fallback serving index.html) or if the body is a bare platform default.
- Source: Next `app/not-found.tsx` or `pages/404.tsx`; Astro `src/pages/404.astro`. SPAs on Vercel/Netlify with a catch-all rewrite to `/index.html` produce soft 404s — need a real 404 route plus host config, or accept WARN for app-only SPAs.

### L4 Framework leaked in tab/header — [high]
No default scaffolding left: title "Vite + React", "Create Next App", "Astro Basics", "React App"; default `vite.svg`/`react.svg`/Next/Astro favicon; `X-Powered-By: Next.js` header; `generator` meta from the starter.
- Live: `live.pages[].title`, `live.headers['x-powered-by']`, `live.favicon`.
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
- Live: `live.pages[].og`; `live.og_image_check` fetches the image and reports status/content-type.
- Common failure: relative `og:image` URL (Next without `metadataBase`; Astro without `site`). That counts as FAIL — scrapers need absolute URLs.
- Next: `app/opengraph-image.(png|tsx)` or `metadata.openGraph.images` + `metadataBase`.

### L8 No structured data — [med]
At least the homepage has JSON-LD (`Organization` or `WebSite`; plus `Article`, `Product`, `BreadcrumbList`, `FAQPage`, `SoftwareApplication` as appropriate). JSON must parse.
- Live: `live.pages[].jsonld_types`, `jsonld_errors`.
- N/A for pages behind auth.

### L9 Multiple H1s — [med]
Each page has exactly one `<h1>`. (HTML5 allows more, but for SEO and screen-reader clarity one is the norm.)
- Live: `live.pages[].h1_count > 1`. Common cause: logo wrapped in `<h1>` in the header plus a page H1.

### L10 No H1 — [high]
Each page has an `<h1>`. Hero text styled big but in a `<div>`/`<p>` counts as missing.
- Live: `live.pages[].h1_count == 0`.

### L11 No canonical tag — [high]
Each indexable page has `<link rel="canonical">` with an absolute URL on the production domain, pointing to itself (or the preferred duplicate).
- Live: `live.pages[].canonical`. FAIL if missing, relative, on a platform hostname, or every page canonicalizes to the homepage (a common bug from a hardcoded root-layout canonical).
- Next: `alternates: { canonical: './' }` per page with `metadataBase`. Astro: `new URL(Astro.url.pathname, Astro.site)`.

### L12 No `llms.txt` — [low]
`/llms.txt` exists: markdown with site name, one-line summary, and links to key pages/docs. Emerging convention — WARN rather than FAIL if missing.
- Live: `live.llms_txt`. Source: `public/llms.txt` or a route.

### L13 AI blocked in `robots.txt` — [med]
`robots.txt` doesn't unintentionally block AI/answer-engine crawlers (`GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `Claude-User`, `Claude-SearchBot`, `anthropic-ai`, `PerplexityBot`, `Google-Extended`, `Applebot-Extended`, `CCBot`) and doesn't `Disallow: /` for `*`.
- Live: `live.robots.blocked_ai_agents`, `live.robots.blocks_all`.
- If the block looks deliberate (comment explaining it), report as PASS with a note — it's a business decision. If `User-agent: * / Disallow: /` is on production, that's a **blocker** (usually a staging robots.txt shipped by accident).
- Also: robots.txt should reference the sitemap (`Sitemap: https://…/sitemap.xml`).

### L14 No favicon — [med]
A favicon is served (`/favicon.ico` or `<link rel="icon">` resolves with 200), ideally plus `apple-touch-icon` (180×180) and it isn't the framework default.
- Live: `live.favicon`. Source: `src.favicon`.

### L15 No `sitemap.xml` — [high]
`/sitemap.xml` (or a sitemap index) exists, is valid XML, lists the public pages with absolute production URLs, and doesn't list noindexed/404 pages.
- Live: `live.sitemap` (status, url count, sample, hostnames used).
- Next: `app/sitemap.ts` or `next-sitemap`. Astro: `@astrojs/sitemap` (needs `site` in config).

### L16 No lang attribute — [high]
`<html lang="en">` (or appropriate language) on every page.
- Live: `live.pages[].lang`. Source: `src.html_lang` (Next root layout `<html lang>`, Pages Router `_document`, Astro layout, Vite `index.html`).

### L17 Missing alt text — [high]
Every `<img>` has an `alt` attribute; meaningful images have descriptive alt; decorative ones use `alt=""`. Also check `next/image` / Astro `<Image>` usages in source.
- Live: `live.pages[].imgs_missing_alt` (count + sample srcs). Source: `src.img_missing_alt`.
- Alt text like "image", "photo", "img_1234.jpg" → WARN.

### L18 Source maps — [high]
Production JS source maps aren't publicly served (they expose original source, comments, sometimes secrets). Uploading them privately to Sentry etc. is fine.
- Live: `live.sourcemaps` (tries `<bundle>.map` and checks `//# sourceMappingURL`). FAIL if a `.map` returns 200 with JSON.
- Source: `src.sourcemaps` — Next `productionBrowserSourceMaps: true`; Vite `build.sourcemap: true` (use `'hidden'` if uploading to Sentry); CRA without `GENERATE_SOURCEMAP=false`; Astro `vite.build.sourcemap`.

### L19 Console errors — [high]
No errors (and ideally no warnings like hydration mismatches, 404'd assets, CSP violations) in the browser console on main pages.
- Needs a browser — see SKILL.md step 3. If none available: NOT VERIFIED, plus list what the static scan suggests (e.g. hydration-risky patterns like `Date.now()`/`Math.random()`/`window` in render, missing assets referenced in HTML that `probe_live` found 404).
- `live.broken_assets` lists referenced scripts/styles/images that 4xx — those always produce console errors, so that's a FAIL even without a browser.

### L20 Massive JS bundles — [high]
Initial JS for the homepage is reasonable. Rough budget (compressed transfer size): ≤ 200 KB good, 200–400 KB WARN, > 400 KB FAIL. A single chunk > 250 KB compressed is a red flag.
- Live: `live.js_bundles` (per-script compressed size and total).
- Source: after `npm run build`, Next prints route sizes ("First Load JS"); Vite prints chunk sizes. Look for whole-library imports (`lodash`, `moment`, icon packs imported via barrel, full `@mui/icons-material`), and heavy libs in client components that could be server-only.

### L21 Title length & word order — [med]
Titles are ~30–60 characters, lead with the page-specific keyword, and put the brand last: `Pricing — Acme` not `Acme | Home | Pricing`. Homepage can be `Acme — <value prop>`.
- Live: `live.pages[].title_length`. WARN for < 15 or > 65 chars or brand-first on inner pages.

### L22 Description quality — [med]
Descriptions are ~70–160 characters, unique per page, describe that page specifically (not the same tagline everywhere), no keyword stuffing, and aren't placeholder text ("Generated by create next app", "My Astro site", lorem ipsum).
- Live: `live.pages[].description_length`, `live.duplicate_descriptions`.

### L23 Heading hierarchy sequential — [med]
Headings don't skip levels going down (h1 → h3 without h2). Going back up is fine.
- Live: `live.pages[].heading_skips`. Often caused by picking heading tags for font size — fix with CSS classes instead.

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
Pages use `<header>`, `<nav>`, `<main>` (exactly one), `<footer>` rather than div soup. Helps screen readers and content extraction.
- Live: `live.pages[].landmarks`. FAIL if no `<main>`; WARN if other landmarks are missing.

### L28 Thin content — [med]
Indexable pages have substantive unique text (rough floor: ~250 words for content/marketing pages; landing pages can be lower if they're clearly purposeful). Placeholder copy ("Lorem ipsum", "Coming soon", "TODO") is a FAIL.
- Live: `live.pages[].word_count`, `live.pages[].placeholder_text`.
- Source: grep for lorem ipsum / TODO copy in page components.

### L29 Descriptive link text — [med]
Links say where they go — no "click here", "read more", "learn more", "here" without context; icon-only links have `aria-label`.
- Live: `live.pages[].vague_links`, `live.pages[].empty_links`.

### L30 Internal link graph — [med]
Every important public page is reachable via normal `<a href>` links from the homepage within a few clicks (not only via JS `onClick` navigation or the sitemap). No orphan pages; no internal links to 404s.
- Live: `live.orphans` (in sitemap but not linked from crawled pages), `live.broken_internal_links`, `live.pages[].internal_link_count`.
- Source: `onClick={() => router.push(...)}` on non-link elements for primary navigation → WARN.

### L31 Freshness & authorship — [low]
Content pages (blog, docs, articles) show a published/updated date and an author; ideally reflected in JSON-LD (`datePublished`, `dateModified`, `author`) and sitemap `<lastmod>`. Footer copyright year is current. N/A for sites with no editorial content.
- Live: `live.pages[].dates_found`, `live.copyright_year`.

### L32 HTTPS & hostname canonicalization — [high]
`http://` → `https://` with a 301/308; `www` and apex resolve to one canonical host (the other redirects with 301/308); no mixed content.
- Live: `live.redirects` (http→https, www↔apex), `live.pages[].mixed_content`.
- Overlaps S19 — evaluate once, report under S19 and reference it here.
