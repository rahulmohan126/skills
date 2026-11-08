#!/usr/bin/env python3
"""Static scan of a React-family repo (Next.js, Astro, Vite/CRA, Remix) for
production-readiness signals. Stdlib only. Prints JSON to stdout.

Usage: scan_source.py <repo-path> [--no-history]

Findings are *leads*: every hit includes file:line so the caller can open it
and confirm. Secrets are redacted to their first 4 chars.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    "node_modules", ".git", ".next", "dist", "build", "out", ".astro", ".vercel",
    ".netlify", ".turbo", "coverage", ".cache", ".output", ".svelte-kit", "storybook-static",
    ".expo", "public/build", ".wrangler",
}
TEXT_EXT = {
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".astro", ".vue", ".svelte",
    ".json", ".html", ".md", ".mdx", ".toml", ".yaml", ".yml", ".sql", ".prisma", ".rules",
    ".txt", ".xml", ".env", ".example", ".sample", ".local", ".production", ".development",
}
CODE_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts", ".astro", ".vue", ".svelte"}
MAX_FILE_BYTES = 600_000
HIT_CAP = 40

SECRET_PATTERNS = [
    ("stripe_secret", r"\b(sk|rk)_(live|test)_[0-9a-zA-Z]{16,}"),
    ("openai_key", r"\bsk-(proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("aws_access_key", r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github_token", r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("slack_token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("sendgrid_key", r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    ("resend_key", r"\bre_[A-Za-z0-9]{8,}_[A-Za-z0-9]{16,}"),
    ("private_key_block", r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    ("supabase_secret_key", r"\bsb_secret_[A-Za-z0-9_-]{20,}"),
    ("db_url_with_password", r"\b(postgres(ql)?|mysql|mongodb(\+srv)?|redis|rediss)://[^\s:'\"@/]+:[^\s@'\"/]{3,}@[^\s'\"]+"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("generic_secret_assignment", r"(?i)\b(secret|password|passwd|api[_-]?key|auth[_-]?token|private[_-]?key)\b\s*[:=]\s*['\"][^'\"\s]{12,}['\"]"),
]
# Google browser keys and Supabase anon JWTs are designed to be public; we still
# report them but tag them so the caller can decide.
PUBLIC_BY_DESIGN = {"google_api_key"}

CLIENT_ENV_PREFIXES = ("NEXT_PUBLIC_", "PUBLIC_", "VITE_", "REACT_APP_", "EXPO_PUBLIC_", "GATSBY_")
SECRETY_NAME = re.compile(r"(?i)(SECRET|SERVICE_ROLE|PRIVATE|PASSWORD|_SK\b|SK_|TOKEN|OPENAI|ANTHROPIC|STRIPE_SECRET|DATABASE_URL|ADMIN)")
SAFE_PUBLIC_NAME = re.compile(r"(?i)(ANON_KEY|PUBLISHABLE|BEACON|SITE_KEY|ANALYTICS|PLAUSIBLE|UMAMI|CLARITY|PIXEL|_PK\b|PK_|SITE_URL|APP_URL|POSTHOG|SENTRY_DSN|GA_|GTM|MEASUREMENT_ID|FIREBASE_API_KEY|PROJECT_ID|AUTH_DOMAIN|STORAGE_BUCKET|MESSAGING_SENDER_ID|APP_ID|MAPS)")

AUTH_CALL = re.compile(
    r"\b(auth\(\)|getServerSession|getSession\(|currentUser\(|getAuth\(|auth\.getUser|getUser\(|"
    r"verifyIdToken|requireUser|requireAuth|withAuth|getKindeServerSession|validateRequest|"
    r"locals\.(user|session)|session\.user|clerkClient|authenticate\(|isAuthenticated|getToken\(|"
    r"api\.getSession|betterAuth|lucia|verifySession|requireSession|checkAuth|ensureAuth)"
)
VALIDATION_CALL = re.compile(r"(\.safeParse\(|\.parse\(|\.parseAsync\(|z\.object|v\.parse\(|safeParse\(|yup\.object|\.validate\(|inputSchema|schema\(|input:\s*z\.)")


def run(cmd, cwd, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def redact(s):
    s = s.strip()
    return (s[:4] + "…" + f"({len(s)} chars)") if len(s) > 6 else "…"


def rel(p, root):
    return str(Path(p).relative_to(root))


def list_files(root, is_git):
    files = []
    if is_git:
        code, out = run(["git", "ls-files", "-co", "--exclude-standard"], root)
        if code == 0:
            for line in out.splitlines():
                parts = Path(line).parts
                if any(part in SKIP_DIRS for part in parts):
                    continue
                files.append(root / line)
            return files
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            files.append(Path(dp) / fn)
    return files


def is_text(p):
    name = p.name
    return p.suffix in TEXT_EXT or name.startswith(".env") or name in {"_headers", "_redirects", "Dockerfile"}


def read(p):
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        return p.read_text(errors="ignore")
    except Exception:  # noqa: BLE001
        return None


def load_pkg(root):
    pkg_path = root / "package.json"
    if not pkg_path.exists():
        return {}
    try:
        return json.loads(pkg_path.read_text())
    except Exception:  # noqa: BLE001
        return {}


def detect(root, pkg, files):
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    names = {rel(f, root) for f in files}

    framework, version = "unknown", None
    if "next" in deps:
        framework, version = "nextjs", deps["next"]
        router = []
        if any(n.startswith(("app/", "src/app/")) for n in names):
            router.append("app")
        if any(n.startswith(("pages/", "src/pages/")) for n in names):
            router.append("pages")
        framework += "(" + "+".join(router or ["?"]) + " router)"
    elif "astro" in deps:
        framework, version = "astro", deps["astro"]
    elif "@remix-run/react" in deps or "@react-router/dev" in deps:
        framework, version = "remix/react-router", deps.get("@remix-run/react") or deps.get("@react-router/dev")
    elif "gatsby" in deps:
        framework, version = "gatsby", deps["gatsby"]
    elif "react-scripts" in deps:
        framework, version = "cra", deps["react-scripts"]
    elif "vite" in deps and "react" in deps:
        framework, version = "vite-react", deps["vite"]
    elif "react" in deps:
        framework, version = "react", deps["react"]

    backend = []
    if any(k.startswith("@supabase/") for k in deps) or (root / "supabase").is_dir():
        backend.append("supabase")
    if "firebase" in deps or "firebase-admin" in deps or (root / "firebase.json").exists():
        backend.append("firebase")
    if "@prisma/client" in deps or "prisma" in deps:
        backend.append("prisma")
    if "drizzle-orm" in deps:
        backend.append("drizzle")
    if "mongoose" in deps or "mongodb" in deps:
        backend.append("mongodb")
    if any(k in deps for k in ("pg", "postgres", "mysql2", "@neondatabase/serverless", "@vercel/postgres", "better-sqlite3", "@planetscale/database", "@libsql/client", "kysely", "knex")):
        backend.append("sql-driver")
    if "convex" in deps:
        backend.append("convex")
    if "@aws-amplify/backend" in deps or "aws-amplify" in deps:
        backend.append("amplify")

    auth = [k for k in deps if k in {
        "next-auth", "@auth/core", "@clerk/nextjs", "@clerk/astro", "@clerk/clerk-react", "lucia",
        "better-auth", "@supabase/ssr", "@supabase/auth-helpers-nextjs", "@kinde-oss/kinde-auth-nextjs",
        "@auth0/nextjs-auth0", "@workos-inc/authkit-nextjs", "@stackframe/stack", "firebase", "iron-session",
    }]

    pm = "npm"
    if (root / "pnpm-lock.yaml").exists():
        pm = "pnpm"
    elif (root / "yarn.lock").exists():
        pm = "yarn"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        pm = "bun"
    elif not (root / "package-lock.json").exists():
        pm = "npm (no lockfile!)"

    return framework, version, backend, auth, pm, deps


TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|e2e|cypress|playwright|mocks?|fixtures|evals)/|\.(test|spec|stories)\.[cm]?[jt]sx?$")


def is_test(path):
    return bool(TEST_PATH.search(path))


def is_client_file(path_rel, text, framework):
    head = text[:400]
    if re.search(r"^\s*['\"]use client['\"]", head, re.M):
        return True
    if framework.startswith(("vite-react", "cra", "react", "gatsby")):
        return not re.search(r"(^|/)(server|api|functions|netlify|supabase/functions)/", path_rel)
    if framework == "astro" and path_rel.endswith((".tsx", ".jsx")) and "/components/" in path_rel:
        return True  # likely islands; caller should confirm
    return False


def scan(root, history=True):
    root = Path(root).resolve()
    is_git = (root / ".git").exists() or run(["git", "rev-parse", "--is-inside-work-tree"], root)[0] == 0
    files = list_files(root, is_git)
    pkg = load_pkg(root)
    framework, version, backend, auth_libs, pm, deps = detect(root, pkg, files)

    R = {
        "repo": str(root), "is_git": is_git, "framework": framework, "framework_version": version,
        "backend": backend, "auth_libs": auth_libs, "package_manager": pm,
        "scripts": pkg.get("scripts", {}),
    }

    def add(key, item):
        lst = R.setdefault(key, [])
        if len(lst) < HIT_CAP:
            lst.append(item)

    texts = {}
    for f in files:
        if f.is_file() and is_text(f):
            t = read(f)
            if t is not None:
                texts[rel(f, root)] = t

    # ---------- S1 / S2: secrets ----------
    for path, t in texts.items():
        if path.endswith((".lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")):
            continue
        is_env_example = re.search(r"\.env\.(example|sample|template)$", path)
        client = is_client_file(path, t, framework)
        for name, pat in SECRET_PATTERNS:
            for m in re.finditer(pat, t):
                line = t.count("\n", 0, m.start()) + 1
                val = m.group(0)
                note = []
                if name == "jwt":
                    note.append("decode payload: role=anon is public-by-design, role=service_role is a secret")
                    try:
                        import base64
                        payload = val.split(".")[1]
                        payload += "=" * (-len(payload) % 4)
                        role = json.loads(base64.urlsafe_b64decode(payload)).get("role")
                        if role:
                            note = [f"jwt role={role}"]
                    except Exception:  # noqa: BLE001
                        pass
                if name in PUBLIC_BY_DESIGN:
                    note.append("usually public-by-design (Firebase web/Maps) — check referrer restrictions")
                if is_env_example:
                    note.append("in env example file — check it's a placeholder")
                add("secret_hits", {"type": name, "file": path, "line": line, "value": redact(val),
                                    "client_side": client, "note": "; ".join(note)})

    # client-prefixed env vars with secret-y names
    env_ref = re.compile(r"\b((?:" + "|".join(CLIENT_ENV_PREFIXES) + r")[A-Z0-9_]+)")
    seen = set()
    for path, t in texts.items():
        for m in env_ref.finditer(t):
            var = m.group(1)
            if var in seen:
                continue
            if SECRETY_NAME.search(var) and not SAFE_PUBLIC_NAME.search(var):
                seen.add(var)
                add("client_env_secrets", {"var": var, "file": path, "line": t.count("\n", 0, m.start()) + 1})

    env_files = [p for p in texts if re.search(r"(^|/)\.env(\.|$)", p)]
    if is_git:
        code, out = run(["git", "ls-files"], root)
        tracked = set(out.splitlines()) if code == 0 else set()
        R["tracked_env_files"] = [p for p in tracked if re.search(r"(^|/)\.env(\.[a-z.]+)?$", p)
                                  and not re.search(r"\.(example|sample|template)$", p)]
        R["tracked_secret_files"] = [p for p in tracked if re.search(
            r"(service[-_]?account.*\.json|firebase-adminsdk.*\.json|\.pem$|\.p12$|\.key$|id_rsa)", p)]
    else:
        R["tracked_env_files"] = "not a git repo"
    gi = (root / ".gitignore").read_text(errors="ignore") if (root / ".gitignore").exists() else ""
    R["gitignore_env"] = bool(re.search(r"^\s*\.env", gi, re.M))
    R["env_files_present"] = env_files

    if is_git and history:
        code, out = run(["git", "log", "-p", "--all", "-n", "400", "--no-color", "--unified=0"], root, timeout=90)
        if code == 0:
            commit = None
            for line in out.splitlines():
                if line.startswith("commit "):
                    commit = line.split()[1][:10]
                elif line.startswith("+") and not line.startswith("+++"):
                    for name, pat in SECRET_PATTERNS:
                        if name in ("generic_secret_assignment", "jwt", "google_api_key"):
                            continue
                        m = re.search(pat, line)
                        if m:
                            add("history_secret_hits", {"type": name, "commit": commit, "value": redact(m.group(0))})
            R.setdefault("history_secret_hits", [])
            R["history_scanned_commits"] = "last 400 across all branches"

    # ---------- S3 / S4: DB clients, RLS, rules ----------
    for path, t in texts.items():
        if Path(path).suffix not in CODE_EXT:
            continue
        for m in re.finditer(r"(createClient|createBrowserClient|createServerClient|initializeApp|admin\.initializeApp|createAdminClient)\s*\(([^)]{0,300})", t):
            key_hint = re.findall(r"[A-Z][A-Z0-9_]{6,}", m.group(2))
            add("db_client_usages", {
                "file": path, "line": t.count("\n", 0, m.start()) + 1, "call": m.group(1),
                "env_vars": key_hint[:4], "client_side": is_client_file(path, t, framework),
                "service_key": bool(re.search(r"(?i)service_role|SERVICE_ROLE|sb_secret|SECRET", m.group(2))),
            })
        if "firebase-admin" in t and is_client_file(path, t, framework):
            add("db_client_usages", {"file": path, "note": "firebase-admin imported in client-side file"})

    if "supabase" in backend:
        sql = {p: t for p, t in texts.items() if p.endswith(".sql")}
        tables, rls = {}, set()
        policies = []
        for p, t in sql.items():
            for m in re.finditer(r"(?i)create\s+table\s+(?:if\s+not\s+exists\s+)?(?:\"?public\"?\.)?\"?(\w+)\"?", t):
                tables[m.group(1).lower()] = p
            for m in re.finditer(r"(?i)alter\s+table\s+(?:only\s+)?(?:\"?public\"?\.)?\"?(\w+)\"?\s+enable\s+row\s+level\s+security", t):
                rls.add(m.group(1).lower())
            for m in re.finditer(r"(?is)create\s+policy\s+\"?([^\"\n]+?)\"?\s+on\s+(?:\"?public\"?\.)?\"?(\w+)\"?(.{0,400}?);", t):
                body = m.group(3)
                policies.append({"table": m.group(2).lower(), "name": m.group(1)[:60], "file": p,
                                 "permissive_true": bool(re.search(r"(?i)using\s*\(\s*true\s*\)|with\s+check\s*\(\s*true\s*\)", body))})
        R["supabase_rls"] = {
            "migrations_found": bool(sql),
            "tables": sorted(tables),
            "tables_without_rls": sorted(t for t in tables if t not in rls),
            "tables_with_rls_no_policy": sorted(t for t in rls if t in tables and not any(p["table"] == t for p in policies)),
            "permissive_true_policies": [p for p in policies if p["permissive_true"]][:20],
            "policy_count": len(policies),
        }
    if "firebase" in backend:
        rules = {}
        for p, t in texts.items():
            if p.endswith((".rules", "database.rules.json")) or "firestore.rules" in p or "storage.rules" in p:
                rules[p] = {
                    "allow_all": bool(re.search(r"allow\s+read\s*,\s*write\s*:\s*if\s+true|allow\s+(read|write)\s*:\s*if\s+true|\"\.(read|write)\"\s*:\s*true", t)),
                    "test_mode_expiry": bool(re.search(r"request\.time\s*<\s*timestamp\.date", t)),
                    "uses_auth": "request.auth" in t or "auth != null" in t or "auth.uid" in t,
                }
        R["firebase_rules"] = rules or "no rules files in repo"

    # ---------- S6 / S14: server entrypoints ----------
    def entry_kind(path, t):
        if re.search(r"(^|/)app/.*route\.(t|j)sx?$", path):
            return "next-route-handler"
        if re.search(r"(^|/)pages/api/", path):
            return "next-api-route"
        if re.search(r"^\s*['\"]use server['\"]", t[:300], re.M):
            return "server-actions-file"
        if re.search(r"(^|/)src/pages/.*\.(t|j)s$", path) and re.search(r"export\s+(const|async function|function)\s+(GET|POST|PUT|PATCH|DELETE|ALL)\b", t):
            return "astro-endpoint"
        if re.search(r"(^|/)src/actions/", path) and "defineAction" in t:
            return "astro-action"
        if re.search(r"(^|/)(app/routes|routes)/", path) and re.search(r"export\s+(async\s+)?(function|const)\s+(loader|action)\b", t):
            return "remix-loader/action"
        if re.search(r"(^|/)(netlify/functions|api|functions|supabase/functions)/", path) and re.search(r"(export\s+(default|const handler|async function handler)|Deno\.serve|serve\()", t):
            return "serverless-function"
        if re.search(r"\b(app|router)\.(get|post|put|patch|delete)\(", t) and "express" in t:
            return "express"
        if re.search(r"(^|/)(src/)?middleware\.(t|j)s$", path):
            return "middleware"
        return None

    for path, t in texts.items():
        if Path(path).suffix not in CODE_EXT:
            continue
        kind = entry_kind(path, t)
        if not kind:
            continue
        inline_use_server = kind != "server-actions-file" and "'use server'" in t or '"use server"' in t
        methods = re.findall(r"export\s+(?:async\s+)?(?:function|const)\s+(GET|POST|PUT|PATCH|DELETE|loader|action)\b", t)
        R.setdefault("server_entrypoints", []).append({
            "file": path, "kind": kind, "methods": sorted(set(methods)),
            "auth_detected": bool(AUTH_CALL.search(t)),
            "has_validation": bool(VALIDATION_CALL.search(t)),
            "webhook_signature": bool(re.search(r"constructEvent|verifyWebhook|Webhook\(|svix|verifySignature|x-hub-signature|stripe-signature", t)),
            "inline_server_actions": inline_use_server,
        })
    # inline server actions in components
    for path, t in texts.items():
        if Path(path).suffix in CODE_EXT and re.search(r"async\s+function\s+\w+\([^)]*\)\s*\{\s*['\"]use server['\"]", t):
            if not any(e["file"] == path for e in R.get("server_entrypoints", [])):
                R.setdefault("server_entrypoints", []).append({
                    "file": path, "kind": "inline-server-action", "auth_detected": bool(AUTH_CALL.search(t)),
                    "has_validation": bool(VALIDATION_CALL.search(t))})
    R.setdefault("server_entrypoints", [])

    # ---------- code-pattern scans ----------
    pattern_scans = {
        "mass_assignment": r"(data:\s*(body|req\.body|await\s+req(uest)?\.json\(\)|input|formData|Object\.fromEntries\(formData\))\b|\.(insert|update|upsert)\(\s*(body|req\.body|data|input|payload)\s*\)|\.\.\.(body|req\.body|input|payload)\b|setDoc\([^,]+,\s*(data|body|input)\s*\))",
        "raw_sql": r"(\$queryRawUnsafe|\$executeRawUnsafe|sql\.raw\(|knex\.raw\(\s*`[^`]*\$\{|\.(query|execute)\(\s*`[^`]*\$\{|\.(query|execute)\(\s*['\"][^'\"]*['\"]\s*\+|\.or\(\s*`[^`]*\$\{|\.filter\(\s*`[^`]*\$\{)",
        "html_injection": r"(dangerouslySetInnerHTML|set:html|\.innerHTML\s*=|v-html|insertAdjacentHTML|document\.write\()",
        "token_in_localstorage": r"localStorage\.setItem\(\s*['\"`][^'\"`]*(token|jwt|session|auth)[^'\"`]*['\"`]",
        "http_urls": r"['\"`]http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|www\.w3\.org|schemas\.|json-schema\.org|xmlns)[^'\"`\s]+",
        "uploads": r"(type=['\"]file['\"]|formData\.get\([^)]*\)\s*as\s+File|instanceof\s+File|multer|formidable|busboy|uploadthing|\.storage\.from\(|getSignedUrl|createPresignedPost|PutObjectCommand|uploadBytes|@vercel/blob)",
        "hydration_risk": r"(\{\s*(new Date\(\)|Date\.now\(\)|Math\.random\(\))|typeof window !== ['\"]undefined['\"]\s*\?)",
    }
    for key, pat in pattern_scans.items():
        rx = re.compile(pat, re.I if key in ("token_in_localstorage",) else 0)
        R.setdefault(key, [])
        for path, t in texts.items():
            if is_test(path):
                continue
            if key == "mass_assignment" and is_client_file(path, t, framework):
                continue
            if Path(path).suffix not in CODE_EXT and not (key == "http_urls" and Path(path).suffix in {".json", ".toml", ".html"}):
                continue
            if key == "http_urls" and path.endswith(("package.json", "tsconfig.json")):
                continue
            for m in rx.finditer(t):
                line_no = t.count("\n", 0, m.start()) + 1
                line_txt = t.splitlines()[line_no - 1].strip()[:160] if t else ""
                item = {"file": path, "line": line_no, "snippet": line_txt}
                if key == "html_injection":
                    item["sanitized_in_file"] = bool(re.search(r"DOMPurify|sanitize-html|sanitizeHtml|rehype-sanitize|xss\(|isomorphic-dompurify", t))
                add(key, item)

    # libraries
    def libs(names):
        return [n for n in names if n in deps]
    R["validation_libs"] = libs(["zod", "valibot", "yup", "joi", "@sinclair/typebox", "arktype", "next-safe-action", "superstruct", "@conform-to/zod"])
    R["rate_limiting"] = libs(["@upstash/ratelimit", "rate-limiter-flexible", "express-rate-limit", "@arcjet/next", "@arcjet/node", "limiter", "@unkey/ratelimit"])
    R["bot_protection"] = libs(["@marsidev/react-turnstile", "react-turnstile", "@hcaptcha/react-hcaptcha", "react-google-recaptcha", "react-google-recaptcha-v3", "@arcjet/next", "botid"])
    if any("turnstile" in t.lower() or "hcaptcha" in t.lower() or "recaptcha" in t.lower() for t in texts.values()):
        R["bot_protection"].append("captcha referenced in code")
    hashing = libs(["bcrypt", "bcryptjs", "argon2", "@node-rs/argon2", "@node-rs/bcrypt", "@oslojs/crypto"])
    weak = []
    for path, t in texts.items():
        if Path(path).suffix in CODE_EXT and re.search(r"(?i)password", t):
            for m in re.finditer(r"createHash\(\s*['\"](md5|sha1|sha256|sha512)['\"]", t):
                weak.append({"file": path, "line": t.count("\n", 0, m.start()) + 1, "algo": m.group(1)})
    stores_pw = any(re.search(r"(?i)(password_?hash|hashed_?password|passwordHash)\b", t) for p, t in texts.items() if p.endswith((".prisma", ".sql", ".ts", ".js")))
    R["password_hashing"] = {"libs": hashing, "weak_hash_near_password": weak[:10], "schema_has_password_column": stores_pw}

    # ---------- headers config ----------
    hdr = {}
    for path, t in texts.items():
        if re.search(r"(^|/)(next\.config\.[mc]?[jt]s|vercel\.json|netlify\.toml|_headers|astro\.config\.[mc]?[jt]s|middleware\.[jt]s|src/middleware\.[jt]s|firebase\.json|wrangler\.toml|staticwebapp\.config\.json)$", path):
            found = [h for h in ["Strict-Transport-Security", "Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"] if h.lower() in t.lower()]
            hdr[path] = found
    R["security_headers_config"] = hdr
    nc = next((t for p, t in texts.items() if re.match(r"next\.config\.[mc]?[jt]s$", p)), "")
    R["next_powered_by_disabled"] = bool(re.search(r"poweredByHeader\s*:\s*false", nc)) if nc else None

    # ---------- SEO / launch source signals ----------
    sm = []
    for path, t in texts.items():
        if re.search(r"productionBrowserSourceMaps\s*:\s*true", t):
            sm.append({"file": path, "setting": "productionBrowserSourceMaps: true"})
        m = re.search(r"sourcemap\s*:\s*(true|['\"]inline['\"]|['\"]hidden['\"])", t)
        if m and re.search(r"(vite|astro)\.config", path):
            sm.append({"file": path, "setting": f"sourcemap: {m.group(1)}"})
        if path.startswith(".env") and re.search(r"GENERATE_SOURCEMAP\s*=\s*false", t):
            sm.append({"file": path, "setting": "GENERATE_SOURCEMAP=false (good)"})
    if framework == "cra" and not any("GENERATE_SOURCEMAP=false" in s["setting"] for s in sm):
        build_script = pkg.get("scripts", {}).get("build", "")
        if "GENERATE_SOURCEMAP=false" not in build_script:
            sm.append({"setting": "CRA default: source maps ON in production build"})
    R["sourcemaps"] = sm

    langs = []
    for path, t in texts.items():
        if re.search(r"(^|/)(index\.html|(src/)?app/(.*/)?(layout|global-not-found)\.[jt]sx?|(src/)?pages/_document\.[jt]sx?|src/layouts/.*\.astro|app/root\.[jt]sx?)$", path):
            # real opening tags only: `<html` followed by whitespace/attrs (skips "<html lang>" in comments)
            for m in re.finditer(r"<html(\s+[^<]*?)?>", t, re.S):
                tag = m.group(0)
                lm = re.search(r"\blang=(\{[^}]+\}|['\"][^'\"]*['\"])", tag)
                if not tag.strip("<>").strip() == "html lang" and (lm or "lang" not in tag):
                    val = lm.group(1).strip("'\"") if lm else None
                    langs.append({"file": path, "line": t.count("\n", 0, m.start()) + 1,
                                  "lang": val, "dynamic": bool(val and val.startswith("{"))})
                    break
    R["html_lang"] = langs

    pub = [n for n in texts] + [rel(f, root) for f in files]
    pubset = set(pub)
    def has(*cands):
        return [c for c in cands if c in pubset]
    R["favicon"] = has("public/favicon.ico", "public/favicon.svg", "public/favicon.png", "app/favicon.ico", "src/app/favicon.ico",
                       "app/icon.png", "app/icon.svg", "app/icon.tsx", "src/app/icon.png", "src/app/icon.svg", "public/apple-touch-icon.png",
                       "app/apple-icon.png", "src/app/apple-icon.png")
    R["robots"] = has("public/robots.txt", "app/robots.ts", "app/robots.js", "src/app/robots.ts", "src/pages/robots.txt.ts", "static/robots.txt")
    R["sitemap"] = has("public/sitemap.xml", "app/sitemap.ts", "app/sitemap.js", "src/app/sitemap.ts", "next-sitemap.config.js", "next-sitemap.config.cjs") + \
        (["@astrojs/sitemap"] if "@astrojs/sitemap" in deps else []) + (["next-sitemap"] if "next-sitemap" in deps else [])
    R["llms_txt"] = has("public/llms.txt", "app/llms.txt/route.ts", "src/app/llms.txt/route.ts", "src/pages/llms.txt.ts")
    R["not_found_page"] = sorted(p for p in pubset if re.search(r"(^|/)(not-found|global-not-found)\.[jt]sx?$|(^|/)404\.(astro|[jt]sx?|html|md)$|app/routes/\$\.[jt]sx?$", p))
    _unused_nf = has("app/not-found.tsx", "app/not-found.jsx", "src/app/not-found.tsx", "pages/404.tsx", "pages/404.jsx", "src/pages/404.tsx", "src/pages/404.astro", "app/routes/$.tsx")
    R["og_image_files"] = [p for p in pubset if re.search(r"(opengraph-image|twitter-image|og[-_]?image|og\.(png|jpg))", p)]

    leftovers = []
    for path, t in texts.items():
        for s in ["Vite + React", "Vite + React + TS", "Create Next App", "Generated by create next app", "React App", "Astro Basics", "Welcome to Astro", "Edit src/App", "Get started by editing"]:
            if s in t and Path(path).suffix in CODE_EXT | {".html"}:
                leftovers.append({"file": path, "text": s})
    for p in ["public/vite.svg", "src/assets/react.svg", "public/next.svg", "public/vercel.svg", "public/favicon.svg" if framework == "astro" else "", "public/logo192.png"]:
        if p and p in pubset:
            leftovers.append({"file": p, "text": "default scaffold asset (check if still used)"})
    R["scaffold_leftovers"] = leftovers

    alt = []
    for path, t in texts.items():
        if Path(path).suffix not in CODE_EXT | {".html", ".mdx"} or is_test(path):
            continue
        for m in re.finditer(r"<(img|Image)(\s+[^<>]*?(?:\{[^}]*\}[^<>]*?)*)/?>", t, re.S):
            if not re.search(r"\balt\s*=", m.group(2)) and "{...props}" not in m.group(2):
                alt.append({"file": path, "line": t.count("\n", 0, m.start()) + 1})
    R["img_missing_alt"] = alt[:HIT_CAP]
    R["raw_img_tags"] = sum(len(re.findall(r"<img\b", t)) for p, t in texts.items() if Path(p).suffix in {".tsx", ".jsx", ".astro"})

    large = []
    for f in files:
        rp = rel(f, root)
        if rp.startswith(("public/", "static/", "src/assets/")) and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp", ".tif", ".tiff"}:
            try:
                sz = f.stat().st_size
                if sz > 300_000:
                    large.append({"file": rp, "kb": sz // 1024})
            except OSError:
                pass
    R["large_public_images"] = sorted(large, key=lambda x: -x["kb"])[:20]

    noindex = []
    for path, t in texts.items():
        if Path(path).suffix in CODE_EXT | {".html", ".json", ".toml"} or path.endswith("_headers"):
            for m in re.finditer(r"(noindex|index\s*:\s*false|X-Robots-Tag)", t):
                noindex.append({"file": path, "line": t.count("\n", 0, m.start()) + 1,
                                "snippet": t.splitlines()[t.count("\n", 0, m.start())].strip()[:160]})
    R["noindex_refs"] = noindex[:HIT_CAP]

    placeholder = []
    for path, t in texts.items():
        if Path(path).suffix in {".tsx", ".jsx", ".astro", ".mdx", ".md", ".html"} and not path.lower().startswith(("readme", "docs/", "changelog")):
            for m in re.finditer(r"(?i)(lorem ipsum|coming soon|your (company|tagline) here|placeholder text)", t):
                placeholder.append({"file": path, "line": t.count("\n", 0, m.start()) + 1, "text": m.group(0)})
    R["placeholder_copy"] = placeholder[:HIT_CAP]

    for p in ("astro.config.mjs", "astro.config.ts", "astro.config.js"):
        if p in texts:
            m = re.search(r"site\s*:\s*['\"]([^'\"]+)", texts[p])
            R["astro_site"] = m.group(1) if m else None
    R["metadata_base"] = [p for p, t in texts.items() if "metadataBase" in t][:5]
    hosts = r"[\w-]+\.(vercel\.app|netlify\.app|pages\.dev|onrender\.com|herokuapp\.com|github\.io|fly\.dev|up\.railway\.app|railway\.app|web\.app|firebaseapp\.com|amplifyapp\.com|surge\.sh)"
    R["platform_hostname_refs"] = [{"file": p, "host": m.group(0)} for p, t in texts.items()
                                   if not p.endswith(("lock", ".lock", "package-lock.json")) for m in [re.search(hosts, t)] if m][:20]

    # ---------- how the build is served ----------
    m = re.search(r"output\s*:\s*['\"](export|standalone)['\"]", nc)
    R["next_output_mode"] = m.group(1) if m else ("server" if framework.startswith("nextjs") else None)
    am = next((t for p, t in texts.items() if re.match(r"astro\.config\.[mc]?[jt]s$", p)), "")
    if am:
        om = re.search(r"output\s*:\s*['\"](static|server|hybrid)['\"]", am)
        R["astro_output_mode"] = om.group(1) if om else "static"
        R["astro_adapter"] = (re.search(r"@astrojs/(node|vercel|netlify|cloudflare)", am) or [None, None])[1]
    R["static_headers_file"] = [p for p in ("public/_headers", "static/_headers") if (root / p).exists()]

    # ---------- build output (only if a build already exists; never builds) ----------
    builds = {}
    for d in ("out", "dist", "build", ".next/static", ".next/standalone", ".output/public"):
        bd = root / d
        if not bd.is_dir():
            continue
        maps, refs, html, js = [], [], 0, 0
        for dp, dns, fns in os.walk(bd):
            dns[:] = [x for x in dns if x != "node_modules"]
            for fn in fns:
                fp = Path(dp) / fn
                if fn.endswith(".map"):
                    maps.append(rel(fp, root))
                elif fn.endswith((".js", ".css", ".mjs")):
                    js += 1
                    try:
                        with open(fp, "rb") as fh:
                            fh.seek(max(0, fp.stat().st_size - 600))
                            tail = fh.read()
                            if b"sourceMappingURL=" in tail and b"sourceMappingURL=data:" not in tail:
                                refs.append(rel(fp, root))
                    except OSError:
                        pass
                elif fn.endswith(".html"):
                    html += 1
        newest = max((f.stat().st_mtime for f in bd.rglob("*") if f.is_file()), default=0)
        builds[d] = {"html_files": html, "js_css_files": js, "map_files": len(maps), "map_sample": maps[:5],
                     "files_referencing_sourcemap": len(refs), "ref_sample": refs[:5], "newest_mtime": int(newest)}
    R["build_output"] = builds or "no build output found (run the build to check source maps in shipped files)"

    # ---------- git state: is what's deployed the code being audited? ----------
    if is_git:
        _, head = run(["git", "rev-parse", "--short", "HEAD"], root)
        _, branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
        _, dirty = run(["git", "status", "--porcelain"], root)
        code, ahead = run(["git", "rev-list", "--count", "@{u}..HEAD"], root)
        _, last = run(["git", "log", "-1", "--format=%ci"], root)
        R["git_state"] = {"head": head.strip(), "branch": branch.strip(), "last_commit": last.strip(),
                          "uncommitted_files": len([l for l in dirty.splitlines() if l.strip()]),
                          "commits_ahead_of_upstream": int(ahead.strip()) if code == 0 and ahead.strip().isdigit() else "no upstream"}
    return R


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    out = scan(sys.argv[1], history="--no-history" not in sys.argv)
    print(json.dumps(out, indent=1))
