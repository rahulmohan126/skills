#!/usr/bin/env python3
"""Probe a live site, a local server, or a built static folder for
production-readiness signals. Stdlib only. Prints JSON to stdout.

Usage:
  probe_live.py <url> [--max-pages N] [--site-host HOST]
  probe_live.py --serve-dir <build-dir> [--max-pages N] [--site-host HOST]

--serve-dir serves a static build (Astro dist/, Next `output: "export"` out/,
Vite dist/) the way a static host does: clean URLs (/about -> about.html or
about/index.html), 404.html with a real 404 status for anything missing, and
response headers from a Cloudflare/Netlify-style `_headers` file in that folder.

A local build emits production URLs (canonical, sitemap, og:image name the real
domain). The site host is detected from the sitemap/canonical (or given with
--site-host) and those URLs are mapped onto the origin being probed.

All requests are read-only GET/HEAD.
"""
import gzip
import json
import os
import re
import ssl
import sys
import threading
import uuid
import zlib
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

UA = "Mozilla/5.0 (compatible; prod-readiness-check/1.0)"
TIMEOUT = 15
PLATFORM_HOSTS = ("vercel.app", "netlify.app", "pages.dev", "workers.dev", "onrender.com", "herokuapp.com",
                  "github.io", "fly.dev", "railway.app", "web.app", "firebaseapp.com", "amplifyapp.com", "surge.sh")
AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
             "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "meta-externalagent",
             "Bytespider", "Amazonbot", "cohere-ai", "Diffbot"]
SEC_HEADERS = ["strict-transport-security", "content-security-policy", "content-security-policy-report-only",
               "x-content-type-options", "x-frame-options", "referrer-policy", "permissions-policy"]
LEAKY_HEADERS = ["x-powered-by", "x-generator", "x-nextjs-cache", "x-aspnet-version"]
SECRET_PATTERNS = [
    ("stripe_secret", r"\b(sk|rk)_(live|test)_[0-9a-zA-Z]{16,}"),
    ("openai_key", r"\bsk-(proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("aws_access_key", r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github_token", r"\b(ghp|gho|ghs)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),
    ("supabase_secret_key", r"\bsb_secret_[A-Za-z0-9_-]{20,}"),
    ("private_key_block", r"-----BEGIN (RSA |EC |)PRIVATE KEY-----"),
    ("db_url_with_password", r"(postgres(ql)?|mysql|mongodb(\+srv)?)://[^\s:'\"@/]+:[^\s@'\"/]{3,}@[^\s'\"]+"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]
VAGUE = {"click here", "here", "read more", "learn more", "more", "link", "this", "go", "details", "continue"}


# ------------------------------------------------------------------ static server

def read_header_rules(d):
    f = Path(d) / "_headers"
    rules = []
    if not f.exists():
        return rules
    for line in f.read_text(errors="ignore").splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if not line[:1].isspace():
            pat = re.escape(line.strip()).replace(r"\*", ".*")
            pat = re.sub(r":\w+", "[^/]+", pat)
            rules.append((re.compile(f"^{pat}$"), []))
        elif rules and ":" in line:
            k, v = line.strip().split(":", 1)
            rules[-1][1].append((k.strip(), v.strip()))
    return rules


def serve_dir(d):
    root = Path(d).resolve()
    rules = read_header_rules(root)

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _resolve(self, path):
            p = unquote(urlparse(path).path)
            for cand in (p, p + ".html", p.rstrip("/") + ".html", p.rstrip("/") + "/index.html"):
                f = (root / ("." + cand)).resolve()
                if str(f).startswith(str(root)) and f.is_file():
                    return f
            return None

        def _send(self, head):
            f = self._resolve(self.path)
            status = 200
            if not f:
                status = 404
                f = root / "404.html"
                body = f.read_bytes() if f.exists() else b"Not Found"
            else:
                body = f.read_bytes()
            self.send_response(status)
            path = urlparse(self.path).path
            for rx, hs in rules:
                if rx.match(path):
                    for k, v in hs:
                        self.send_header(k, v)
            self.send_header("Content-Type", self.guess_type(str(f)) if f.exists() else "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def do_GET(self):
            self._send(False)

        def do_HEAD(self):
            self._send(True)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv, bool(rules)


# ------------------------------------------------------------------ http

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = build_opener()
opener_noredir = build_opener(NoRedirect())


def fetch(url, method="GET", follow=True, max_bytes=8_000_000):
    req = Request(url, method=method, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Accept": "*/*"})
    try:
        resp = (opener if follow else opener_noredir).open(req, timeout=TIMEOUT)
        status, headers, final = resp.status, resp.headers, resp.geturl()
        raw = resp.read(max_bytes) if method == "GET" else b""
    except HTTPError as e:
        status, headers, final = e.code, e.headers, url
        try:
            raw = e.read(max_bytes) if method == "GET" else b""
        except Exception:  # noqa: BLE001
            raw = b""
    except (URLError, ssl.SSLError, TimeoutError, ConnectionError, OSError) as e:
        return {"url": url, "error": str(e)[:200]}
    enc = (headers.get("Content-Encoding") or "").lower()
    try:
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
    except Exception:  # noqa: BLE001
        pass
    return {"url": url, "final_url": final, "status": status,
            "headers": {k.lower(): v for k, v in headers.items()},
            "set_cookies": headers.get_all("Set-Cookie") or [],
            "raw": raw, "body": raw.decode("utf-8", errors="ignore")}


# ------------------------------------------------------------------ html

class PageParser(HTMLParser):
    SKIP = ("script", "style", "noscript", "template", "svg")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.in_title = "", False
        self.meta, self.links, self.headings, self.imgs, self.anchors = [], [], [], [], []
        self.scripts, self.styles, self.jsonld = [], [], []
        self.html_lang, self.landmarks = None, {}
        self._script_type, self._buf, self._in_script = None, [], False
        self._a_stack, self._skip, self._heading = [], 0, None
        self.text_parts, self.main_parts, self._in_main = [], [], 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta.append(a)
        elif tag == "link":
            self.links.append(a)
            if "stylesheet" in a.get("rel", "") and a.get("href"):
                self.styles.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
            if self._a_stack and a.get("alt"):
                self._a_stack[-1]["img_alt"] = a["alt"]
        elif tag == "script":
            self._in_script, self._script_type, self._buf = True, a.get("type", ""), []
            if a.get("src"):
                self.scripts.append({"src": a["src"], "type": a.get("type"), "nomodule": "nomodule" in a})
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), []]
        elif tag == "a":
            self._a_stack.append({"href": a.get("href"), "aria": a.get("aria-label") or a.get("title"), "text": [], "img_alt": ""})
        if tag in ("header", "nav", "main", "footer", "aside"):
            self.landmarks[tag] = self.landmarks.get(tag, 0) + 1
        if tag == "main" or a.get("role") == "main":
            self._in_main += 1
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script":
            if self._in_script and "ld+json" in (self._script_type or ""):
                self.jsonld.append("".join(self._buf))
            self._in_script = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            self.headings.append((self._heading[0], " ".join("".join(self._heading[1]).split())[:80]))
            self._heading = None
        if tag == "a" and self._a_stack:
            x = self._a_stack.pop()
            x["text"] = " ".join("".join(x["text"]).split())
            self.anchors.append(x)
        if tag == "main" and self._in_main:
            self._in_main -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self._in_script:
            self._buf.append(data)
            return
        if self._skip:
            return
        if self._heading:
            self._heading[1].append(data)
        for x in self._a_stack:
            x["text"].append(data)
        self.text_parts.append(data)
        if self._in_main:
            self.main_parts.append(data)


def meta_val(meta, key):
    for m in meta:
        if (m.get("name") or m.get("property") or "").lower() == key:
            return m.get("content")
    return None


def check_jsonld(blocks):
    types, errors, ids, refs = [], [], set(), []
    for raw in blocks:
        if "<" in raw:
            errors.append('raw "<" inside JSON-LD block (breaks parsing / script-injection risk)')
        try:
            d = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            errors.append(f"does not parse: {str(e)[:60]}")
            continue

        def visit(node, top):
            if isinstance(node, list):
                for n in node:
                    visit(n, top)
                return
            if not isinstance(node, dict):
                return
            if top and "@context" not in node:
                errors.append("top-level node without @context")
            t = node.get("@type")
            if t:
                types.extend(t if isinstance(t, list) else [t])
            if "@id" in node:
                (ids.add(node["@id"]) if len(node) > 1 else refs.append(node["@id"]))
            for k, v in node.items():
                if k != "@context":
                    visit(v, False)
        visit(d, True)
    dangling = sorted(set(r for r in refs if r not in ids))
    return types, errors, dangling


def word_count(parts):
    return len(re.findall(r"[A-Za-zÀ-ɏ]{2,}", " ".join(parts)))


def analyze_page(url, res, map_url, origin_host):
    p = PageParser()
    try:
        p.feed(res["body"])
    except Exception:  # noqa: BLE001
        pass
    text = " ".join(" ".join(p.text_parts).split())
    title = " ".join(p.title.split())
    desc = meta_val(p.meta, "description")
    robots = " ".join(filter(None, [meta_val(p.meta, "robots"), meta_val(p.meta, "googlebot"), res["headers"].get("x-robots-tag")]))
    canonical = next((l.get("href") for l in p.links if l.get("rel", "").lower() == "canonical"), None)
    og = {k: meta_val(p.meta, k) for k in ("og:title", "og:description", "og:image", "og:url", "og:type", "twitter:card", "twitter:image")}
    levels = [h[0] for h in p.headings]
    skips, prev = [], 0
    for lvl, txt in p.headings:
        if lvl > prev + 1:
            skips.append(f"h{prev or '∅'}->h{lvl} \"{txt[:30]}\"")
        prev = lvl
    no_alt = [i.get("src", "")[:100] for i in p.imgs if "alt" not in i]
    empty_alt = sum(1 for i in p.imgs if "alt" in i and not i["alt"].strip())
    weak_alt = [i["alt"] for i in p.imgs if i.get("alt", "").strip().lower() in {"image", "img", "photo", "picture"}
                or re.search(r"\.(png|jpe?g|webp|gif)$", i.get("alt", ""), re.I)]
    internal, vague, empty = [], [], []
    for a in p.anchors:
        href = a.get("href")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = map_url(urljoin(url, href))
        if urlparse(absu).netloc == origin_host:
            internal.append(norm_path(urlparse(absu).path))
        label = (a["text"] or a.get("aria") or a.get("img_alt") or "").strip()
        if not label:
            empty.append(href[:80])
        elif label.lower() in VAGUE:
            vague.append(f"{label} -> {href[:60]}")
    jt, je, dangling = check_jsonld(p.jsonld)
    emitted = [x for x in [canonical, og.get("og:url"), og.get("og:image"), og.get("twitter:image")] if x]
    emitted += [l.get("href") for l in p.links if l.get("rel") == "alternate" and l.get("href")]
    emitted += [s["src"] for s in p.scripts] + p.styles + [i.get("src", "") for i in p.imgs] + [a.get("href") or "" for a in p.anchors]
    insecure = sorted({e for e in emitted if e.startswith("http://") and not re.match(r"http://(localhost|127\.)", e)})
    gen = meta_val(p.meta, "generator")
    images = [{"src": i.get("src", "")[:100], "has_dims": bool(i.get("width") and i.get("height")),
               "loading": i.get("loading") or None, "fetchpriority": i.get("fetchpriority") or None,
               "fmt": (re.search(r"\.(\w{3,4})(\?|$)", i.get("src", "")) or [None, None])[1], "srcset": bool(i.get("srcset"))}
              for i in p.imgs[:40]]
    return {
        "path": norm_path(urlparse(url).path), "status": res.get("status"),
        "title": title, "title_length": len(title),
        "description": desc, "description_length": len(desc) if desc else 0,
        "canonical": canonical, "lang": p.html_lang, "og": og, "meta_generator": gen,
        "h1_count": levels.count(1), "h1s": [h[1] for h in p.headings if h[0] == 1][:3],
        "heading_outline": " ".join(f"h{l}" for l in levels[:40]), "heading_skips": skips[:5],
        "jsonld_types": sorted(set(jt)), "jsonld_errors": je, "jsonld_dangling_ids": dangling[:5],
        "imgs_total": len(p.imgs), "imgs_no_alt_attr": {"count": len(no_alt), "sample": no_alt[:5]},
        "imgs_empty_alt": empty_alt, "weak_alt": weak_alt[:5], "images": images,
        "noindex": bool(re.search(r"noindex|\bnone\b", robots, re.I)), "robots_directives": robots or None,
        "landmarks": p.landmarks,
        "word_count": word_count(p.text_parts), "main_word_count": word_count(p.main_parts) if p.main_parts else None,
        "text_chars": len(text),
        "empty_shell": len(text) < 300 and bool(re.search(r'<div id=["\'](root|app|__next)["\']>\s*</div>', res["body"])),
        "placeholder_text": sorted(set(m.lower() for m in re.findall(r"(?i)lorem ipsum|coming soon|placeholder text|your tagline", text)))[:3],
        "internal_links": len(set(internal)), "vague_links": vague[:6], "empty_links": empty[:6],
        "insecure_urls": insecure[:8],
        "dates_found": [" ".join(d) for d in re.findall(r"(?i)(published|updated|last updated|posted)[^\n]{0,40}?\b(20\d\d)", text)[:3]],
        "favicon_links": [l.get("href") for l in p.links if "icon" in l.get("rel", "").lower()],
        "has_apple_touch_icon": any(l.get("rel") == "apple-touch-icon" for l in p.links),
        "has_manifest": any(l.get("rel") == "manifest" for l in p.links),
        "_internal": list(dict.fromkeys(internal)), "_scripts": p.scripts, "_styles": p.styles, "_body": res["body"],
    }


def norm_path(path):
    return (path.rstrip("/") or "/")


# ------------------------------------------------------------------ robots

def parse_robots(text):
    groups, sitemaps, g, last_agent = [], [], None, False
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        m = re.match(r"^([\w-]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2).strip()
        if k == "sitemap":
            sitemaps.append(v)
        elif k == "user-agent":
            if not last_agent:
                g = {"agents": [], "allow": [], "disallow": []}
                groups.append(g)
            g["agents"].append(v.lower())
        elif g and k in ("allow", "disallow"):
            g[k].append(v)
        last_agent = k == "user-agent"
    return {"groups": groups, "sitemaps": sitemaps}


def robots_blocks(rb, agent, path):
    """Longest match wins, Allow breaks ties; a named group replaces '*'."""
    named = [g for g in rb["groups"] if agent.lower() in g["agents"]]
    groups = named or [g for g in rb["groups"] if "*" in g["agents"]]
    rules = [(p, True) for g in groups for p in g["allow"]] + [(p, False) for g in groups for p in g["disallow"] if p]
    def rx(p):
        end = p.endswith("$")
        body = re.escape(p.rstrip("$")).replace(r"\*", ".*")
        return re.compile("^" + body + ("$" if end else ""))
    matching = [(p, allow) for p, allow in rules if rx(p).match(path)]
    matching.sort(key=lambda x: (-len(x[0]), not x[1]))
    return bool(matching) and not matching[0][1]


def sitemap_locs(url, fetch_fn, depth=0):
    r = fetch_fn(url)
    if "error" in r or r["status"] != 200 or "<html" in r["body"][:300].lower():
        return {"url": url, "status": r.get("status"), "error": r.get("error"), "urls": []}
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r["body"])
    if "<sitemapindex" in r["body"] and depth < 1:
        urls = []
        for sub in locs[:10]:
            urls += sitemap_locs(sub, fetch_fn, depth + 1)["urls"]
        return {"url": url, "status": 200, "index": True, "children": locs[:10], "urls": urls}
    return {"url": url, "status": 200, "urls": locs, "has_lastmod": "<lastmod>" in r["body"]}


# ------------------------------------------------------------------ main

def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    max_pages = int(arg("--max-pages", 60))
    R = {}
    if "--serve-dir" in sys.argv:
        d = arg("--serve-dir")
        origin, srv, has_rules = serve_dir(d)
        R["mode"] = f"static build served from {d} (headers from _headers: {has_rules})"
        is_local = True
    else:
        origin = sys.argv[1].rstrip("/")
        if not origin.startswith("http"):
            origin = "https://" + origin
        is_local = urlparse(origin).hostname in ("localhost", "127.0.0.1", "0.0.0.0")
        R["mode"] = "local server" if is_local else "deployed site"
    R["origin"] = origin
    home = fetch(origin + "/")
    if "error" in home:
        R["fatal"] = f"could not fetch homepage: {home['error']}"
        print(json.dumps(R, indent=1))
        return
    if not is_local:
        fu = urlparse(home["final_url"])
        if fu.netloc != urlparse(origin).netloc:
            R["homepage_redirected_to"] = home["final_url"]
            origin = f"{fu.scheme}://{fu.netloc}"
    oh = urlparse(origin).netloc

    # site host: what the site calls itself
    rb_res = fetch(origin + "/robots.txt")
    robots_ok = rb_res.get("status") == 200 and "<html" not in rb_res.get("body", "")[:300].lower()
    rb = parse_robots(rb_res["body"]) if robots_ok else {"groups": [], "sitemaps": []}
    sm_candidates = [s for s in rb["sitemaps"]] + ["/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml"]
    site_host = arg("--site-host")

    def map_url(u):
        pu = urlparse(u)
        if site_host and pu.netloc in (site_host, "www." + site_host, site_host.removeprefix("www.")) and pu.netloc != oh:
            return origin + (pu.path or "/") + (("?" + pu.query) if pu.query else "")
        return u

    def fetch_site(u, **kw):
        return fetch(map_url(urljoin(origin + "/", u)), **kw)

    sm = {"urls": []}
    for cand in sm_candidates:
        if not site_host and cand.startswith("http"):
            site_host = urlparse(cand).netloc
        sm = sitemap_locs(map_url(urljoin(origin + "/", cand)) if cand.startswith("/") else cand, fetch_site)
        if sm["urls"]:
            break
    home_canon = next(iter(re.findall(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', home["body"])), None)
    if not site_host:
        cand = (sm["urls"][:1] or [home_canon or ""])[0]
        site_host = urlparse(cand).netloc or oh
    R["site_host"] = site_host
    R["platform_hostname"] = next((h for h in PLATFORM_HOSTS if site_host.endswith(h) or oh.endswith(h)), None)

    # headers
    hh = home["headers"]
    R["headers"] = {k: v for k, v in hh.items() if k in SEC_HEADERS + LEAKY_HEADERS + ["server", "x-robots-tag", "cache-control", "x-vercel-id", "x-nf-request-id", "cf-ray"]}
    R["security_headers"] = {h: (hh.get(h) or "MISSING") for h in SEC_HEADERS}
    R["security_headers"]["frame_protection"] = bool(hh.get("x-frame-options") or "frame-ancestors" in (hh.get("content-security-policy") or ""))
    m = re.search(r"max-age=(\d+)", hh.get("strict-transport-security", ""))
    R["hsts"] = {"max_age": int(m.group(1)) if m else None, "preload": "preload" in hh.get("strict-transport-security", "")}
    R["leaky_headers"] = {h: hh[h] for h in LEAKY_HEADERS if hh.get(h)}
    R["cookies"] = [{"name": c.split("=")[0], "httponly": "httponly" in c.lower(), "secure": "secure" in c.lower(),
                     "samesite": (re.search(r"samesite=(\w+)", c, re.I) or [None, None])[1]} for c in home["set_cookies"]]

    # redirects (deployed only)
    red = {}
    if not is_local:
        h = urlparse(origin).netloc
        r = fetch(f"http://{h}/", follow=False)
        red["http_to_https"] = {"status": r.get("status"), "location": r.get("headers", {}).get("location"), "error": r.get("error"),
                                "ok": bool(r.get("status") in (301, 302, 307, 308) and (r.get("headers", {}).get("location") or "").startswith("https://"))}
        alt = h[4:] if h.startswith("www.") else "www." + h
        r2 = fetch(f"https://{alt}/", follow=False)
        red["alt_host"] = {"host": alt, "status": r2.get("status"), "location": r2.get("headers", {}).get("location"),
                           "error": r2.get("error"), "both_serve_200": r2.get("status") == 200}
    R["redirects"] = red or "not checked (local)"

    # robots
    R["robots"] = {"status": rb_res.get("status"), "html_fallback": rb_res.get("status") == 200 and not robots_ok,
                   "sitemap_lines": rb["sitemaps"],
                   "blocks_all_for_star": robots_blocks(rb, "*", "/") if robots_ok else None,
                   "blocked_ai_agents": [a for a in AI_AGENTS if robots_ok and robots_blocks(rb, a, "/")],
                   "groups": [{"agents": g["agents"], "disallow": g["disallow"][:6], "allow": g["allow"][:4]} for g in rb["groups"]][:12]}

    # sitemap
    locs = sm["urls"]
    R["sitemap"] = {k: v for k, v in sm.items() if k != "urls"}
    R["sitemap"].update({"url_count": len(locs), "sample": locs[:5], "hosts": sorted({urlparse(x).netloc for x in locs}),
                         "duplicates": sorted({x for x in locs if locs.count(x) > 1})[:10],
                         "insecure": [x for x in locs if x.startswith("http://")][:5],
                         "blocked_by_robots": [x for x in locs if robots_ok and robots_blocks(rb, "Googlebot", urlparse(x).path or "/")][:10]})

    # llms.txt
    ll = fetch(origin + "/llms.txt")
    lb = ll.get("body") or ""
    is_html = "<html" in lb[:500].lower()
    R["llms_txt"] = {"status": ll.get("status"), "html_fallback": is_html, "bytes": len(ll.get("raw") or b""),
                     "has_h1": bool(re.search(r"^# \S", lb, re.M)), "has_summary_blockquote": bool(re.search(r"^> \S", lb, re.M)),
                     "has_sections": bool(re.search(r"^## \S", lb, re.M))} if ll.get("status") == 200 and not is_html else {"status": ll.get("status"), "html_fallback": is_html}

    # crawl: sitemap paths first, then links
    paths = list(dict.fromkeys(["/"] + [norm_path(urlparse(x).path) for x in locs]))
    pages, seen, queue = [], set(), list(paths)
    while queue and len(pages) < max_pages:
        path = queue.pop(0)
        if path in seen or re.search(r"\.(png|jpe?g|gif|svg|webp|avif|pdf|zip|xml|txt|ico|css|js|json|mp4|webm)$", path, re.I):
            continue
        seen.add(path)
        r = home if path == "/" else fetch(origin + path)
        if "error" in r:
            pages.append({"path": path, "status": None, "error": r["error"]})
            continue
        if not (r["headers"].get("content-type") or "").startswith("text/html"):
            continue
        pg = analyze_page(origin + path, r, map_url, oh)
        pages.append(pg)
        for x in pg["_internal"]:
            if x not in seen:
                queue.append(x)
    R["crawl_truncated"] = bool(queue) and len(pages) >= max_pages
    good = [p for p in pages if p.get("status") == 200 and "_body" in p]
    R["sitemap"]["entries_not_200"] = [p["path"] + f" -> {p['status']}" for p in pages if p["path"] in paths and p.get("status") != 200][:10]
    sitemap_paths = set(paths)
    R["pages_linked_not_in_sitemap"] = sorted({p["path"] for p in good if p["path"] not in sitemap_paths and not p["noindex"]})[:15]
    R["sitemap_noindexed"] = [p["path"] for p in good if p["path"] in sitemap_paths and p["noindex"]][:10]

    # link graph
    inbound = {p["path"]: 0 for p in good}
    broken = {}
    for p in good:
        for t in set(p["_internal"]):
            if t != p["path"] and t in inbound:
                inbound[t] += 1
    known = {p["path"]: p.get("status") for p in pages}
    for p in good:
        for t in set(p["_internal"]):
            if t in known and known[t] not in (200, None):
                broken.setdefault(t, {"status": known[t], "from": p["path"]})
    unchecked = [t for p in good for t in p["_internal"] if t not in known][:30]
    for t in dict.fromkeys(unchecked):
        r = fetch(origin + t, method="HEAD")
        if r.get("status") == 405:
            r = fetch(origin + t)
        if r.get("status") and r["status"] >= 400:
            broken.setdefault(t, {"status": r["status"]})
    R["link_graph"] = {"zero_inbound": sorted(k for k, v in inbound.items() if v == 0 and k != "/")[:15],
                       "min_inbound": min([v for k, v in inbound.items() if k != "/"], default=None),
                       "broken_internal_links": [{"path": k, **v} for k, v in list(broken.items())[:15]]}

    # duplicates & title patterns
    def dups(field):
        d = {}
        for p in good:
            v = (p.get(field) or "").strip()
            if v and not p["noindex"]:
                d.setdefault(v, []).append(p["path"])
        return {k[:90]: v[:6] for k, v in d.items() if len(v) > 1}
    R["duplicate_titles"] = dups("title")
    R["duplicate_descriptions"] = dups("description")
    leads = [re.split(r"\s[|·—–:-]\s", p["title"])[0] for p in good if p["title"]]
    common = max(set(leads), key=leads.count) if leads else None
    R["brand_first_titles"] = {"lead": common, "count": leads.count(common), "of": len(leads)} if common and leads.count(common) > max(1, len(leads) / 2) else None
    canon = [p["canonical"] for p in good if p["canonical"]]
    R["all_canonicals_same"] = len(good) > 2 and len(set(canon)) == 1 and len(canon) == len(good)
    R["canonical_problems"] = []
    for p in good:
        c = p["canonical"]
        if not c:
            R["canonical_problems"].append(f"{p['path']}: missing")
            continue
        cu = urlparse(c)
        if not c.startswith("http"):
            R["canonical_problems"].append(f"{p['path']}: relative ({c})")
        elif cu.netloc != site_host:
            R["canonical_problems"].append(f"{p['path']}: other host ({cu.netloc})")
        elif norm_path(cu.path) != p["path"]:
            R["canonical_problems"].append(f"{p['path']}: points to {cu.path}")
    R["canonical_problems"] = R["canonical_problems"][:15]
    tot_img = sum(p["imgs_total"] for p in good)
    tot_empty = sum(p["imgs_empty_alt"] for p in good)
    R["alt_summary"] = {"imgs": tot_img, "no_alt_attr": sum(p["imgs_no_alt_attr"]["count"] for p in good),
                        "empty_alt": tot_empty, "empty_share": round(tot_empty / tot_img, 2) if tot_img else 0}

    # soft 404: root + inside each "section" of the sitemap (dynamic routes)
    probes = [f"/this-page-should-not-exist-{uuid.uuid4().hex[:6]}"]
    parents = {}
    for p in paths:
        segs = p.strip("/").split("/")
        if len(segs) >= 2:
            parents.setdefault("/" + "/".join(segs[:-1]), 0)
            parents["/" + "/".join(segs[:-1])] += 1
    probes += [f"{par}/not-a-real-slug-{uuid.uuid4().hex[:4]}" for par, n in sorted(parents.items(), key=lambda x: -x[1]) if n >= 2][:6]
    R["soft_404"] = []
    for pr in probes:
        nf = fetch(origin + pr)
        body = nf.get("body") or ""
        txt = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", body))
        R["soft_404"].append({"path": pr, "status": nf.get("status"), "is_soft_404": nf.get("status") == 200,
                              "title": (re.search(r"(?is)<title[^>]*>(.*?)</title>", body) or [None, None])[1],
                              "text_chars": len(" ".join(txt.split())), "links_home": bool(re.search(r'href=["\'](/|https?://[^"\']+/)["\']', body))})

    # favicon / OG image
    first = good[0] if good else None
    fav = fetch(origin + "/favicon.ico", max_bytes=200_000)
    link_icon = (first or {}).get("favicon_links") or []
    li = fetch_site(link_icon[0], max_bytes=200_000) if link_icon else None
    R["favicon"] = {"favicon_ico": {"status": fav.get("status"), "content_type": fav.get("headers", {}).get("content-type")},
                    "link_icon": {"href": link_icon[0], "status": li.get("status")} if li else None,
                    "apple_touch_icon": (first or {}).get("has_apple_touch_icon"), "manifest": (first or {}).get("has_manifest")}
    og_checks = {}
    for p in good:
        img = p["og"].get("og:image")
        if img and img not in og_checks and len(og_checks) < 5:
            r = fetch_site(img, max_bytes=100_000)
            og_checks[img] = {"absolute": img.startswith("http"), "status": r.get("status"),
                              "content_type": r.get("headers", {}).get("content-type"), "used_on": p["path"]}
    R["og_images"] = og_checks
    R["pages_missing_og"] = [p["path"] for p in good if not all(p["og"].get(k) for k in ("og:title", "og:description", "og:image"))][:15]

    # JS weight per page (real gzip of first-party scripts), source maps, secrets in bundles
    sizes, maps, secret_hits, broken_assets = {}, [], [], []
    def js_size(src):
        if src not in sizes:
            r = fetch_site(src)
            if "error" in r or r["status"] >= 400:
                broken_assets.append({"url": src[-100:], "status": r.get("status"), "error": r.get("error")})
                sizes[src] = (0, "")
            else:
                sizes[src] = (len(gzip.compress(r["raw"], 9)), r["body"])
        return sizes[src][0]
    heaviest = []
    for p in good[:25]:
        # nomodule scripts are never fetched by module-capable browsers; third-party scripts are excluded
        srcs = {s["src"] for s in p["_scripts"] if not s["nomodule"] and
                (not re.match(r"https?://", s["src"]) or urlparse(s["src"]).netloc in (oh, site_host))}
        kb = round(sum(js_size(s) for s in srcs) / 1024, 1)
        heaviest.append({"path": p["path"], "kb_gzip": kb, "scripts": len(srcs)})
    heaviest.sort(key=lambda x: -x["kb_gzip"])
    largest = sorted(((round(v[0] / 1024, 1), k[-80:]) for k, v in sizes.items()), reverse=True)[:6]
    R["js_weight"] = {"heaviest_pages": heaviest[:6], "largest_chunks_kb_gzip": largest,
                      "note": "first-party <script src> per page, gzip -9; dynamic imports not counted"}
    for src, (_, body) in sizes.items():
        if not body:
            continue
        m = re.search(r"//# sourceMappingURL=(\S+)", body[-600:])
        if m and not m.group(1).startswith("data:"):
            mu = urljoin(map_url(urljoin(origin + "/", src)), m.group(1))
        else:
            mu = map_url(urljoin(origin + "/", src)) + ".map"
        mr = fetch(mu, max_bytes=4000)
        if mr.get("status") == 200 and ('"mappings"' in mr.get("body", "") or '"sources"' in mr.get("body", "")):
            maps.append(mu[-90:])
        for name, pat in SECRET_PATTERNS:
            for mm in re.finditer(pat, body):
                val, note = mm.group(0), ""
                if name == "jwt":
                    try:
                        import base64
                        pl = val.split(".")[1]
                        pl += "=" * (-len(pl) % 4)
                        role = json.loads(base64.urlsafe_b64decode(pl)).get("role")
                        if role == "anon":
                            continue
                        note = f"role={role}"
                    except Exception:  # noqa: BLE001
                        pass
                if len(secret_hits) < 20:
                    secret_hits.append({"type": name, "bundle": src[-60:], "value": val[:4] + "…", "note": note})
    R["sourcemaps_served"] = maps[:10]
    R["bundle_secret_hits"] = secret_hits
    for p in good[:10]:
        for s in p["_styles"][:6]:
            r = fetch_site(s, method="HEAD")
            if r.get("status") and r["status"] >= 400:
                broken_assets.append({"url": s, "status": r["status"], "page": p["path"]})
        for im in p["images"][:12]:
            if im["src"] and not im["src"].startswith("data:"):
                r = fetch_site(im["src"], method="HEAD")
                cl = int((r.get("headers") or {}).get("content-length") or 0)
                if r.get("status") and r["status"] >= 400:
                    broken_assets.append({"url": im["src"], "status": r["status"], "page": p["path"]})
                elif cl > 300_000:
                    R.setdefault("large_images", []).append({"src": im["src"], "kb": cl // 1024, "page": p["path"]})
    R["broken_assets"] = broken_assets[:20]

    er = fetch(f"{origin}/api/__probe_{uuid.uuid4().hex[:6]}?id=%27%22")
    R["error_leak"] = {"status": er.get("status"), "stack_trace": bool(re.search(r"(at \w+ \(|Traceback|node_modules/|\.js:\d+:\d+|PrismaClient|SQLSTATE|ECONNREFUSED)", er.get("body") or ""))}
    years = re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d)", (first or {}).get("_body", ""), re.I)
    R["copyright_year"] = max(years) if years else None

    for p in pages:
        for k in ("_internal", "_scripts", "_styles", "_body"):
            p.pop(k, None)
    R["pages_crawled"] = len(pages)
    R["pages"] = pages
    print(json.dumps(R, indent=1, default=str))


if __name__ == "__main__":
    main()
