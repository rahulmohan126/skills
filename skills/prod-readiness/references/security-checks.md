# Security checks (S1–S20)

Severity tags: **[blocker]** fix before launch · **[high]** should fix before launch · **[med]** fix soon.

These checks are about what an attacker can do with your deployed app and its public client bundle. A useful mental model: **anything that reaches the browser is public** — env vars with a client prefix, JS bundles, source maps, API responses, and every Server Action / API route (an attacker can call them directly with curl, with any body).

Client-exposed env prefixes: Next `NEXT_PUBLIC_*` · Astro `PUBLIC_*` · Vite `VITE_*` · CRA `REACT_APP_*` · Expo `EXPO_PUBLIC_*`. Also anything imported into a `"use client"` file, an Astro `client:*` island, or any Vite/CRA source file.

## Contents
- Secrets: S1–S3
- Data access & authorization: S4–S8
- Auth & sessions: S9–S12
- Input & output handling: S13–S17
- Transport & supply chain: S18–S20

---

## Secrets

### S1 Hide API keys — [blocker]
No secret credentials in client-shipped code or client-prefixed env vars. Secrets = anything that grants write access, costs money, or reads private data: Stripe `sk_live_`/`sk_test_`/`rk_`, OpenAI `sk-`/`sk-proj-`, Anthropic `sk-ant-`, AWS `AKIA…` + secret, GitHub `ghp_`/`github_pat_`, Resend `re_`, SendGrid `SG.`, Twilio auth token, Supabase `service_role` JWT, Firebase Admin private key, DB connection strings with passwords, JWT signing secrets, webhook secrets.
- Source: `src.secret_hits` (tracked files), `src.client_env_secrets` (client-prefixed vars whose *name* implies a secret: `NEXT_PUBLIC_*SECRET*`, `*_SERVICE_ROLE*`, `*PRIVATE*`, `*_SK*`, `OPENAI`, `STRIPE_SECRET`…). Confirm each by opening the file.
- Live: grep the downloaded JS bundles — `live.bundle_secret_hits`. A hit here is confirmed exposure.
- Not secrets (PASS): Supabase anon/publishable key, Firebase web `apiKey`, Stripe `pk_`, Google Maps browser key *restricted by referrer*, Sentry DSN, PostHog/Plausible project keys. These are designed to be public — see S3.
- Fix: move the call server-side (route handler / server action / Astro endpoint), use a non-prefixed env var, **rotate the key** (it's already compromised if it shipped).

### S2 Purge Git secrets — [blocker]
No secrets in git history, and no `.env*` files (other than `.env.example` with placeholder values) are tracked.
- Source: `src.tracked_env_files`, `src.history_secret_hits` (scans `git log -p` for key patterns — capped for speed), `src.gitignore_env` (whether `.env*` is ignored).
- If secrets are found in history: **rotate first** (if the repo was ever pushed, assume the key is leaked). Then optionally rewrite history with `git filter-repo` or BFG and force-push — explain that this is destructive and requires collaborators to re-clone. Never run the rewrite yourself without explicit confirmation.
- Recommend `gitleaks` / GitHub secret scanning / a pre-commit hook going forward.

### S3 Use public DB key — [blocker]
The browser uses only the key that's meant to be public, and that key is safe *because* access rules are enforced (S4).
- Supabase: client uses the `anon` / `sb_publishable_…` key; the `service_role` / `sb_secret_…` key is used only in server code (route handlers, server actions, edge functions) and never with a client env prefix. Check `createClient(` calls: which key, in which file, and is that file client-side?
- Firebase: client uses the web config; `firebase-admin` and service-account JSON only on the server, and the JSON file isn't tracked or in `public/`.
- Own API: browser never gets a DB connection string; there's no direct DB access from the client at all.
- Source: `src.backend`, `src.db_client_usages` (each `createClient`/`initializeApp`/`admin` usage with file, key var, and whether the file is client-side).

## Data access & authorization

### S4 Enable row-level security — [blocker when browser talks to DB directly]
If the browser queries the DB directly (Supabase client, Firestore client SDK), every table/collection the client can reach is protected by rules.
- Supabase: RLS enabled on every table in exposed schemas (usually `public`), with policies — RLS enabled with no policies denies everything (safe but probably broken); `using (true)` on `select` for user data is effectively public. Look in `supabase/migrations/*.sql` for `create table` without matching `enable row level security`, and policies. `src.supabase_rls` does a first pass. If migrations aren't in the repo, ask the user to run in the SQL editor: `select schemaname, tablename, rowsecurity from pg_tables where schemaname='public';` — mark NOT VERIFIED until then.
- Firebase: `firestore.rules` / `storage.rules` / `database.rules.json` exist and aren't `allow read, write: if true;` or test-mode `request.time < timestamp.date(...)`. `src.firebase_rules`.
- Own API with no client DB access: N/A (authorization is covered by S6–S7).

### S5 Encrypt sensitive data — [high]
Highly sensitive fields (government IDs, health data, bank details, third-party OAuth refresh tokens, API keys users give you) are encrypted at the application level or stored in a vault, not plaintext columns. Passwords are hashed, not encrypted (S10). Transport encryption is S19; disk encryption by the hosting DB is assumed.
- Source: look at schema (Prisma `schema.prisma`, Drizzle schema, SQL migrations) for columns like `ssn`, `tax_id`, `dob`, `card`, `iban`, `access_token`, `refresh_token`, `api_key`. If present and stored as plain `text`/`String` with no encryption helper in the write path → FAIL. If none exist → N/A.
- Also: never store full card numbers — use Stripe et al.

### S6 Enforce server-side auth — [blocker]
Every route handler, API route, Server Action, Astro endpoint, and server function that reads or writes non-public data verifies the session **on the server**. Hiding a button in the UI, or a client-side redirect, is not auth.
- Source: `src.server_entrypoints` lists every route/action file and whether an auth call was detected (`auth()`, `getServerSession`, `currentUser`, `supabase.auth.getUser`, `getAuth`, `verifyIdToken`, `locals.user`, Clerk/Lucia/Better Auth helpers). Open each one marked "no auth detected" and decide: is it intentionally public (webhook with signature check, public form, health check) or a hole?
- Next middleware alone isn't sufficient when the matcher misses routes or for Server Actions — and it should not be the only layer (see CVE-2025-29927 class of bypasses). Prefer checks inside each handler/action or a shared data-access layer.
- Supabase: on the server use `getUser()` (verifies with the auth server), not `getSession()` (trusts the cookie).
- Webhooks: must verify signatures (Stripe `constructEvent`, Svix, etc.).

### S7 Lock record access — [blocker]
Being logged in isn't enough — users can only read/modify **their own** records (or their org's). Guards against IDOR: `GET /api/invoices/123` returning someone else's invoice.
- Source: in each handler that takes an ID from params/body, check the query is scoped by the session user (`where: { id, userId: session.user.id }`) or ownership is checked after fetching. Supabase/Firebase: RLS/rules compare `auth.uid()` / `request.auth.uid` to an owner column.
- Admin-only routes check a role from the server-side session/DB, not from a client-sent field or a mutable `user_metadata`.

### S8 Block field tampering — [blocker]
Clients can't set fields they shouldn't: `role`, `isAdmin`, `userId`/`ownerId`, `price`, `credits`, `plan`, `verified`, `stripeCustomerId`. Mass-assignment happens when the request body is spread directly into a DB write.
- Source: `src.mass_assignment` flags patterns like `create({ data: body })`, `update({ data: req.body })`, `.insert(body)`, `.update({...body})`, `setDoc(ref, data)` with unfiltered input. Confirm and recommend a schema (zod) that whitelists fields, with server-set fields (owner, timestamps, price from DB) assigned on the server.
- Supabase: RLS `with check` and column privileges / triggers for protected columns; never trust `user_metadata` for roles (users can edit it) — use `app_metadata` or a roles table.
- Prices must come from the server (Stripe Price IDs looked up server-side), never from the client.

## Auth & sessions

### S9 Secure session cookies — [high]
Session/auth cookies are `HttpOnly`, `Secure`, `SameSite=Lax` (or `Strict`), with sensible expiry. Tokens are not stored in `localStorage` (readable by any XSS).
- Live: `live.cookies` from responses (only catches cookies set without login). Source: `cookies().set(`/`Set-Cookie`/`serialize(` options; `localStorage.setItem(` with token-ish keys → `src.token_in_localstorage`.
- Most auth libraries (NextAuth/Auth.js, Clerk, Supabase SSR, Lucia, Better Auth) set good defaults — PASS with a note if one is used without overrides.

### S10 Hash passwords — [blocker if you store passwords]
If the app stores passwords itself, they're hashed with argon2id, bcrypt (cost ≥ 10), or scrypt — not MD5/SHA-*, not encrypted, not plaintext. N/A if auth is fully delegated (Supabase Auth, Clerk, Auth0, Firebase Auth, OAuth-only).
- Source: `src.password_hashing` (detects bcrypt/argon2/scrypt imports, and `createHash('md5'|'sha1'|'sha256')` near "password").

### S11 Rate limit login — [high]
Login, signup, password reset, OTP/magic-link, and other expensive or abusable endpoints (AI calls, email sending, contact forms) are rate limited per IP and/or account.
- Source: `src.rate_limiting` (Upstash `@upstash/ratelimit`, `rate-limiter-flexible`, `express-rate-limit`, Arcjet, Vercel WAF/firewall config, Cloudflare rules in repo). Managed auth (Supabase, Clerk, Auth0, Firebase) rate-limits its own auth endpoints — PASS for login if so, but still check custom endpoints like AI routes and forms.
- No limiter on an endpoint that calls a paid API (OpenAI, email, SMS) → FAIL; that's a direct cost-abuse risk.

### S12 Add bot protection — [med]
Public forms (signup, contact, waitlist, comments, checkout) have bot protection: Cloudflare Turnstile, hCaptcha, reCAPTCHA, Arcjet, Vercel BotID, or at least a honeypot + server validation. Token is verified **server-side**.
- Source: `src.bot_protection`. N/A if there are no public forms.

## Input & output handling

### S13 Parameterize queries — [blocker]
No SQL built by string concatenation/interpolation with user input. ORM/query builders (Prisma, Drizzle, Kysely, Supabase client) are parameterized by default — but their raw escape hatches aren't.
- Source: `src.raw_sql` flags template-literal SQL passed to `query(`, `execute(`, `$queryRawUnsafe`, `$executeRawUnsafe`, `sql.raw(`, `knex.raw(` with `${}`, and Supabase `.rpc` / `.or(`/`.filter(` built from raw user strings. Prisma's tagged `$queryRaw\`...${x}\`` *is* parameterized → PASS. Also NoSQL: Mongo queries built from unvalidated `req.body` objects (operator injection like `{ "$gt": "" }`).

### S14 Validate all input — [high]
All server entrypoints validate body/params/query/search params against a schema (zod, valibot, yup, Astro actions' `input`, `next-safe-action`) — types, lengths, formats, enums — and reject unexpected fields.
- Source: `src.validation_libs` and per-entrypoint `has_validation` in `src.server_entrypoints`. Server Actions taking `FormData` and using `formData.get()` values directly without validation → FAIL.
- TypeScript types are not validation — they vanish at runtime.

### S15 Escape user content — [blocker if user content is rendered]
User-generated content is rendered safely. React escapes `{text}` by default — the risks are the escape hatches:
- `dangerouslySetInnerHTML` (React), `set:html` (Astro), `innerHTML =`, `v-html`, rendering markdown → HTML without sanitization, `href={userUrl}` without blocking `javascript:` URLs, user data placed inside `<script>` (e.g. JSON-LD built from user input without escaping `</script>`).
- Source: `src.html_injection` lists each usage. PASS if the content is static/trusted or passes through DOMPurify / `sanitize-html` / `rehype-sanitize`. CSP (S18) is defense in depth, not a substitute.

### S16 Restrict file uploads — [high]
If users can upload: server-side checks on size, MIME type *and* magic bytes / extension allowlist; files stored outside the web root or in object storage with non-guessable keys; SVG/HTML either disallowed or served with `Content-Disposition: attachment` / from a separate domain; storage bucket policies restrict who can write/read (Supabase Storage policies, Firebase `storage.rules`, S3 bucket not public-write; presigned URLs with short expiry and content-type/length conditions).
- Source: `src.uploads`. N/A if there are no uploads.

### S17 Trim API responses — [high]
APIs return only the fields the client needs — no `passwordHash`, internal IDs of other users, emails of other users, tokens, full user objects, or stack traces/DB errors in production.
- Source: look for `return Response.json(user)` / `res.json(await prisma.user.findMany())` without `select`. Supabase `select('*')` on tables with sensitive columns accessed from the client. Next Server Components passing full DB rows as props to Client Components — those props are serialized into the page HTML/RSC payload.
- Live: `live.error_leak` (requests a malformed API path; flags stack traces in responses).

## Transport & supply chain

### S18 Add security headers — [high]
Production responses include:
- `Strict-Transport-Security: max-age=31536000; includeSubDomains` (≥ 6 months)
- `Content-Security-Policy` (at least `frame-ancestors`, `object-src 'none'`, `base-uri`; a full script policy is ideal — WARN if absent, FAIL only if there's no CSP *and* there are S15 risks)
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY|SAMEORIGIN` or CSP `frame-ancestors`
- `Referrer-Policy: strict-origin-when-cross-origin` (or stricter)
- `Permissions-Policy` restricting unused features (camera, microphone, geolocation) — WARN if absent
- No `X-Powered-By`, no verbose `Server` version.
- Live: `live.security_headers` (present/missing/value per header, plus `frame_protection`), `live.hsts`, `live.leaky_headers` — authoritative. `--serve-dir` applies a `_headers` file the way Cloudflare Pages/Netlify do, so it reflects that config but not anything the host adds.
- A `Content-Security-Policy-Report-Only` header counts as "CSP in progress" → WARN, not FAIL. When recommending a CSP, ship it report-only first: a strict policy breaks inline styles/scripts and third-party tags.
- HSTS `preload`: only meaningful once submitted at hstspreload.org, and submitting commits **every subdomain** to HTTPS. If `preload` is present, mention this; drop the token if that's not intended.
- `_headers` / `next.config` `headers()` often don't cover everything — e.g. `_headers` applies to static assets, not responses from a Worker or API function. Note which responses the config covers. Source: `src.security_headers_config` (next.config `headers()`, middleware, `vercel.json`, `netlify.toml`/`_headers`, `astro.config` / adapter config) — use when there's no live URL.
- Also covers L25.

### S19 Force HTTPS — [blocker]
All traffic is HTTPS: `http://` redirects (301/308) to `https://`, HSTS set (S18), no mixed content, valid certificate, and no hardcoded `http://` API/asset URLs in source.
- Live: `live.redirects.http_to_https.ok`, `live.pages[].insecure_urls`. A certificate problem surfaces as a fetch error on the https origin. Source: `src.http_urls` (non-localhost `http://` URLs in code/config).
- Also covers L32.

### S20 Scan dependencies — [high]
No known high/critical vulnerabilities in production dependencies, and the framework itself is on a patched version (Next.js has had serious advisories — e.g. middleware auth bypass, RSC/Server Actions RCE class issues — so an old minor is a real risk).
- Run the lockfile's tool: `npm audit --omit=dev --json`, `pnpm audit --prod --json`, `yarn npm audit --environment production` (berry) / `yarn audit --groups dependencies` (classic), `bun audit`. `scan_source.py` reports the package manager and framework version in `src.package_manager`, `src.framework_version`. Requires network; if offline → NOT VERIFIED.
- FAIL on any critical, or high-severity in a runtime dependency with a fix available. Note dev-only issues separately (lower priority).
- Recommend Dependabot/Renovate going forward.
