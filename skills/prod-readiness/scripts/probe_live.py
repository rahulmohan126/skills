#!/usr/bin/env python3
"""Probe a live (or locally served) site for production-readiness signals.
Stdlib only. Prints JSON to stdout.

Usage: probe_live.py <url> [--max-pages N]

Crawls the homepage plus pages from sitemap.xml and internal links (same host),
then reports per-page SEO/a11y signals and site-wide checks (headers, redirects,
robots, sitemap, llms.txt, favicon, soft 404, bundles, source maps, secrets in
bundles). All checks are read-only GET/HEAD requests.
"""
import gzip
import json
import re
import ssl
import sys
import uuid
import zlib
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

UA = "Mozilla/5.0 (compatible; prod-readiness-check/1.0)"
TIMEOUT = 15
PLATFORM_HOSTS = ("vercel.app", "netlify.app", "pages.dev", "onrender.com", "herokuapp.com", "github.io",
                  "fly.dev", "railway.app", "web.app", "firebaseapp.com", "amplifyapp.com", "surge.sh")
AI_AGENTS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
             "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "Bytespider", "meta-externalagent"]
SEC_HEADERS = ["strict-transport-security", "content-security-policy", "x-content-type-options", "x-frame-options",
               "referrer-policy", "permissions-policy"]
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


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


CTX = ssl.create_default_context()
opener = build_opener()
opener_noredir = build_opener(NoRedirect())


def fetch(url, method="GET", follow=True, max_bytes=3_000_000):
    req = Request(url, method=method, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate", "Accept": "*/*"})
    op = opener if follow else opener_noredir
    try:
        resp = op.open(req, timeout=TIMEOUT)
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
    compressed_len = len(raw)
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
            "body": raw.decode("utf-8", errors="ignore"), "compressed_bytes": compressed_len,
            "encoding": enc or None}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.in_title = "", False
        self.meta, self.links, self.headings, self.imgs, self.anchors = [], [], [], [], []
        self.scripts, self.styles, self.jsonld = [], [], []
        self.html_lang, self.landmarks = None, {}
        self._script_type, self._buf, self._in_script = None, [], False
        self._a_stack = []
        self.text_parts, self._skip = [], 0
        self._heading = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta.append(a)
        elif tag == "link":
            self.links.append(a)
            if "stylesheet" in (a.get("rel") or "") and a.get("href"):
                self.styles.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "script":
            self._in_script, self._script_type, self._buf = True, (a.get("type") or ""), []
            if a.get("src"):
                self.scripts.append({"src": a["src"], "type": a.get("type"), "async": "async" in a, "defer": "defer" in a})
            self._skip += 1
        elif tag in ("style", "noscript", "template", "svg"):
            self._skip += 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = [int(tag[1]), []]
        elif tag in ("header", "nav", "main", "footer", "aside"):
            self.landmarks[tag] = self.landmarks.get(tag, 0) + 1
        elif tag == "a":
            self._a_stack.append({"href": a.get("href"), "aria": a.get("aria-label") or a.get("title"), "text": [], "has_img_alt": False})
        if tag == "img" and self._a_stack and a.get("alt"):
            self._a_stack[-1]["has_img_alt"] = True
        role = a.get("role")
        if role in ("main", "navigation", "banner", "contentinfo"):
            self.landmarks[f"role={role}"] = self.landmarks.get(f"role={role}", 0) + 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "script":
            if self._in_script and "ld+json" in self._script_type:
                self.jsonld.append("".join(self._buf))
            self._in_script = False
            self._skip = max(0, self._skip - 1)
        elif tag in ("style", "noscript", "template", "svg"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            self.headings.append((self._heading[0], " ".join("".join(self._heading[1]).split())[:100]))
            self._heading = None
        elif tag == "a" and self._a_stack:
            x = self._a_stack.pop()
            x["text"] = " ".join("".join(x["text"]).split())
            self.anchors.append(x)

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


def meta_val(meta, key):
    for m in meta:
        if (m.get("name") or m.get("property") or "").lower() == key:
            return m.get("content")
    return None


def jsonld_types(blocks):
    types, errors = [], []
    for b in blocks:
        try:
            d = json.loads(b)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e)[:80])
            continue
        stack = d if isinstance(d, list) else [d]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                t = x.get("@type")
                if t:
                    types.extend(t if isinstance(t, list) else [t])
                stack.extend(x.get("@graph", []) if isinstance(x.get("@graph"), list) else [])
    return types, errors


VAGUE = {"click here", "here", "read more", "learn more", "more", "link", "this", "go", "details", "continue"}


def analyze_page(url, res, host):
    p = PageParser()
    try:
        p.feed(res["body"])
    except Exception:  # noqa: BLE001
        pass
    text = " ".join(" ".join(p.text_parts).split())
    words = len(re.findall(r"[A-Za-zÀ-ɏ]{2,}", text))
    title = " ".join(p.title.split())
    desc = meta_val(p.meta, "description")
    robots = (meta_val(p.meta, "robots") or "") + " " + (meta_val(p.meta, "googlebot") or "")
    canonical = next((l.get("href") for l in p.links if (l.get("rel") or "").lower() == "canonical"), None)
    og = {k: meta_val(p.meta, k) for k in ("og:title", "og:description", "og:image", "og:url", "og:type", "twitter:card", "twitter:image")}
    levels = [h[0] for h in p.headings]
    skips = []
    for a, b in zip(levels, levels[1:]):
        if b > a + 1:
            skips.append(f"h{a}->h{b}")
    imgs_missing = [i.get("src", "")[:100] for i in p.imgs if "alt" not in i]
    bad_alt = [i.get("alt") for i in p.imgs if (i.get("alt") or "").strip().lower() in {"image", "img", "photo", "picture", "logo"}
               or re.search(r"\.(png|jpe?g|webp|gif)$", (i.get("alt") or ""), re.I)]
    internal, external = [], 0
    vague, empty = [], []
    for a in p.anchors:
        href = a.get("href")
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(url, href)
        if urlparse(absu).netloc == host:
            internal.append(absu.split("#")[0])
        else:
            external += 1
        t = a["text"].strip().lower()
        if t in VAGUE:
            vague.append(a["text"])
        if not t and not a.get("aria") and not a.get("has_img_alt"):
            empty.append(href[:80])
    jt, je = jsonld_types(p.jsonld)
    mixed = []
    if url.startswith("https://"):
        for s in [x["src"] for x in p.scripts] + p.styles + [i.get("src", "") for i in p.imgs]:
            if s.startswith("http://"):
                mixed.append(s[:100])
    images = [{"src": (i.get("src") or "")[:100], "has_dims": bool(i.get("width") and i.get("height")),
               "loading": i.get("loading"), "fmt": (re.search(r"\.(\w{3,4})(\?|$)", i.get("src") or "") or [None, None])[1],
               "srcset": bool(i.get("srcset"))} for i in p.imgs[:30]]
    dates = re.findall(r"(?i)(published|updated|last updated|posted)[^\n]{0,40}?\b(20\d\d)", text)[:5]
    return {
        "url": url, "status": res.get("status"), "final_url": res.get("final_url"),
        "title": title, "title_length": len(title),
        "description": desc, "description_length": len(desc) if desc else 0,
        "canonical": canonical, "lang": p.html_lang, "og": og,
        "h1_count": levels.count(1), "h1s": [h[1] for h in p.headings if h[0] == 1][:3],
        "heading_outline": [f"h{l}" for l in levels][:40], "heading_skips": skips,
        "jsonld_types": jt, "jsonld_errors": je,
        "imgs_total": len(p.imgs), "imgs_missing_alt": {"count": len(imgs_missing), "sample": imgs_missing[:5]},
        "weak_alt": bad_alt[:5], "images": images,
        "noindex": "noindex" in robots.lower() or "noindex" in (res["headers"].get("x-robots-tag") or "").lower(),
        "landmarks": p.landmarks, "word_count": words,
        "empty_shell": words < 50 and bool(re.search(r'<div id=["\'](root|app|__next)["\']>\s*</div>', res["body"])),
        "placeholder_text": re.findall(r"(?i)lorem ipsum|coming soon|placeholder", text)[:3],
        "internal_link_count": len(set(internal)), "external_link_count": external,
        "vague_links": vague[:8], "empty_links": empty[:8], "mixed_content": mixed[:8],
        "dates_found": [" ".join(d) for d in dates], "favicon_links": [l.get("href") for l in p.links if "icon" in (l.get("rel") or "").lower()],
        "_internal": list(dict.fromkeys(internal)), "_scripts": p.scripts, "_styles": p.styles, "_body": res["body"],
    }


def parse_robots(body):
    groups, cur, sitemaps = [], None, []
    for line in body.splitlines():
        line = line.split("#")[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if cur is None or cur["rules"]:
                cur = {"agents": [], "rules": []}
                groups.append(cur)
            cur["agents"].append(v)
        elif k in ("disallow", "allow") and cur is not None:
            cur["rules"].append((k, v))
        elif k == "sitemap":
            sitemaps.append(v)
    def blocks_root(agent):
        for g in groups:
            if any(a.lower() == agent.lower() for a in g["agents"]):
                return any(k == "disallow" and v == "/" for k, v in g["rules"])
        return None
    star = None
    for g in groups:
        if "*" in g["agents"]:
            star = any(k == "disallow" and v == "/" for k, v in g["rules"])
    blocked = [a for a in AI_AGENTS if blocks_root(a) or (blocks_root(a) is None and star)]
    return {"blocks_all": bool(star), "blocked_ai_agents": blocked, "sitemap_refs": sitemaps,
            "groups": [{"agents": g["agents"], "rules": g["rules"][:6]} for g in groups][:15]}


def parse_sitemap(url, depth=0):
    r = fetch(url)
    if "error" in r or r["status"] != 200:
        return {"url": url, "status": r.get("status"), "error": r.get("error"), "urls": []}
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r["body"])
    if "<sitemapindex" in r["body"] and depth < 1:
        urls = []
        for sub in locs[:5]:
            urls += parse_sitemap(sub, depth + 1)["urls"]
        return {"url": url, "status": 200, "index": True, "children": locs[:10], "urls": urls}
    return {"url": url, "status": 200, "urls": locs, "has_lastmod": "<lastmod>" in r["body"]}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    base = sys.argv[1].rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    max_pages = int(sys.argv[sys.argv.index("--max-pages") + 1]) if "--max-pages" in sys.argv else 15
    u = urlparse(base)
    host = u.netloc
    R = {"base": base, "host": host}
    R["platform_hostname"] = next((h for h in PLATFORM_HOSTS if host.endswith(h)), None)
    R["is_local"] = host.split(":")[0] in ("localhost", "127.0.0.1", "0.0.0.0")

    home = fetch(base + "/")
    if "error" in home:
        R["fatal"] = f"could not fetch homepage: {home['error']}"
        print(json.dumps(R, indent=1))
        return
    final_host = urlparse(home["final_url"]).netloc
    if final_host and final_host != host:
        R["homepage_redirected_to"] = home["final_url"]
        host = final_host
        base = f"{urlparse(home['final_url']).scheme}://{host}"
    R["headers"] = {k: v for k, v in home["headers"].items() if k in SEC_HEADERS + ["server", "x-powered-by", "x-robots-tag", "content-type", "cache-control", "x-vercel-id", "x-nf-request-id", "cf-ray"]}
    R["security_headers"] = {h: (home["headers"].get(h) or "MISSING") for h in SEC_HEADERS}
    hsts = home["headers"].get("strict-transport-security", "")
    m = re.search(r"max-age=(\d+)", hsts)
    R["hsts_max_age"] = int(m.group(1)) if m else None
    R["cookies"] = [{"name": c.split("=")[0], "httponly": "httponly" in c.lower(), "secure": "secure" in c.lower(),
                     "samesite": (re.search(r"samesite=(\w+)", c, re.I) or [None, None])[1]} for c in home["set_cookies"]]
    R["tls_ok"] = base.startswith("https://")

    # redirects
    red = {}
    if not R["is_local"]:
        r = fetch(f"http://{host}/", follow=False)
        red["http_to_https"] = {"status": r.get("status"), "location": r.get("headers", {}).get("location"), "error": r.get("error")}
        bare = host[4:] if host.startswith("www.") else host
        alt = bare if host.startswith("www.") else "www." + host
        r2 = fetch(f"https://{alt}/", follow=False)
        red["alt_host"] = {"host": alt, "status": r2.get("status"), "location": r2.get("headers", {}).get("location"), "error": r2.get("error")}
    R["redirects"] = red

    # robots / sitemap / llms / favicon
    rb = fetch(base + "/robots.txt")
    R["robots"] = {"status": rb.get("status")}
    if rb.get("status") == 200 and "<html" not in rb["body"][:500].lower():
        R["robots"].update(parse_robots(rb["body"]))
    elif rb.get("status") == 200:
        R["robots"]["note"] = "returned HTML (SPA fallback) — no real robots.txt"
    sm_urls = R["robots"].get("sitemap_refs") or [base + "/sitemap.xml"]
    sm = parse_sitemap(sm_urls[0])
    if not sm["urls"] and sm_urls[0] != base + "/sitemap.xml":
        sm = parse_sitemap(base + "/sitemap.xml")
    if not sm["urls"]:
        alt_sm = parse_sitemap(base + "/sitemap-index.xml")
        if alt_sm["urls"]:
            sm = alt_sm
    R["sitemap"] = {k: v for k, v in sm.items() if k != "urls"}
    R["sitemap"]["url_count"] = len(sm["urls"])
    R["sitemap"]["sample"] = sm["urls"][:5]
    R["sitemap"]["hosts"] = sorted({urlparse(x).netloc for x in sm["urls"]})
    ll = fetch(base + "/llms.txt")
    R["llms_txt"] = {"status": ll.get("status"), "is_html_fallback": "<html" in (ll.get("body") or "")[:500].lower(),
                     "preview": (ll.get("body") or "")[:200] if ll.get("status") == 200 else None}

    # soft 404
    rnd = f"{base}/this-page-should-not-exist-{uuid.uuid4().hex[:8]}"
    nf = fetch(rnd)
    nfp = analyze_page(rnd, nf, host) if "error" not in nf else {}
    R["soft_404"] = {"status": nf.get("status"), "is_soft_404": nf.get("status") == 200,
                     "title": nfp.get("title"), "has_link_home": any(urlparse(x).path in ("", "/") for x in nfp.get("_internal", []))}

    # crawl
    queue = [base + "/"] + [x for x in sm["urls"] if urlparse(x).netloc == host][: max_pages]
    seen, pages = set(), []
    first = analyze_page(base + "/", home, host)
    pages.append(first)
    seen.add(base + "/")
    queue += first["_internal"]
    for url in queue:
        if len(pages) >= max_pages:
            break
        nu = urlunparse(urlparse(url)._replace(fragment="", query=""))
        if nu in seen or urlparse(nu).netloc != host:
            continue
        if re.search(r"\.(png|jpe?g|gif|svg|webp|pdf|zip|xml|txt|ico|css|js)$", nu, re.I):
            continue
        seen.add(nu)
        r = fetch(nu)
        if "error" in r or not (r["headers"].get("content-type") or "").startswith("text/html"):
            continue
        pg = analyze_page(nu, r, host)
        pages.append(pg)
        for x in pg["_internal"]:
            if x not in seen and len(queue) < 200:
                queue.append(x)

    linked = set()
    for pg in pages:
        linked.update(urlunparse(urlparse(x)._replace(fragment="", query="")).rstrip("/") for x in pg["_internal"])
    R["orphans"] = [x for x in sm["urls"] if x.rstrip("/") not in linked and x.rstrip("/") != base][:15]
    R["broken_internal_links"] = []
    checked = 0
    for x in sorted(linked):
        if checked >= 40:
            break
        if any(p["url"].rstrip("/") == x for p in pages):
            continue
        checked += 1
        r = fetch(x, method="HEAD")
        if r.get("status") and r["status"] >= 400 and r["status"] != 405:
            R["broken_internal_links"].append({"url": x, "status": r["status"]})
    R["sitemap_urls_broken"] = [p["url"] for p in pages if p["status"] and p["status"] >= 400]

    def dups(field):
        seen_v = {}
        for pg in pages:
            v = (pg.get(field) or "").strip()
            if v and not pg["noindex"]:
                seen_v.setdefault(v, []).append(pg["url"])
        return {k: v for k, v in seen_v.items() if len(v) > 1}
    R["duplicate_titles"] = dups("title")
    R["duplicate_descriptions"] = dups("description")
    canon = [pg["canonical"] for pg in pages if pg["canonical"]]
    R["all_canonicals_same"] = len(pages) > 2 and len(set(canon)) == 1 and len(canon) == len(pages)

    # favicon
    fav_href = (first["favicon_links"] or ["/favicon.ico"])[0]
    fr = fetch(urljoin(base + "/", fav_href), method="GET", max_bytes=200_000)
    R["favicon"] = {"href": fav_href, "status": fr.get("status"), "content_type": fr.get("headers", {}).get("content-type"),
                    "declared_links": first["favicon_links"], "apple_touch_icon": any("apple" in (l or "") for l in first["favicon_links"])}

    # OG image
    og_img = first["og"].get("og:image")
    if og_img:
        r = fetch(urljoin(base + "/", og_img), max_bytes=50_000)
        R["og_image_check"] = {"url": og_img, "absolute": og_img.startswith("http"), "status": r.get("status"),
                               "content_type": r.get("headers", {}).get("content-type")}
    else:
        R["og_image_check"] = None

    # JS bundles, source maps, secrets in bundles, broken assets
    bundles, maps, secret_hits, broken = [], [], [], []
    scripts = [s for s in first["_scripts"]]
    total = 0
    for s in scripts[:25]:
        src = urljoin(base + "/", s["src"])
        r = fetch(src, max_bytes=8_000_000)
        if "error" in r or r["status"] >= 400:
            broken.append({"url": src, "status": r.get("status"), "error": r.get("error")})
            continue
        same = urlparse(src).netloc == host
        size = r["compressed_bytes"]
        if not r["encoding"]:
            size = int(len(r["body"].encode()) * 0.3)  # estimate gzip
        total += size if same else 0
        bundles.append({"url": src[-90:], "kb_compressed": round(size / 1024, 1), "first_party": same,
                        "estimated": not r["encoding"]})
        if same:
            body = r["body"]
            m = re.search(r"//# sourceMappingURL=(\S+)", body[-500:])
            map_url = urljoin(src, m.group(1)) if m and not m.group(1).startswith("data:") else src + ".map"
            mr = fetch(map_url, max_bytes=2000)
            if mr.get("status") == 200 and '"mappings"' in (mr.get("body") or "") or (mr.get("status") == 200 and '"version"' in (mr.get("body") or "")[:200]):
                maps.append(map_url[-90:])
            for name, pat in SECRET_PATTERNS:
                for mm in re.finditer(pat, body):
                    val = mm.group(0)
                    note = ""
                    if name == "jwt":
                        try:
                            import base64
                            pl = val.split(".")[1]
                            pl += "=" * (-len(pl) % 4)
                            role = json.loads(base64.urlsafe_b64decode(pl)).get("role")
                            note = f"role={role}"
                            if role == "anon":
                                continue
                        except Exception:  # noqa: BLE001
                            pass
                    secret_hits.append({"type": name, "bundle": src[-60:], "value": val[:4] + "…", "note": note})
                    if len(secret_hits) > 20:
                        break
    for s in first["_styles"][:10]:
        src = urljoin(base + "/", s)
        r = fetch(src, method="HEAD")
        if r.get("status") and r["status"] >= 400:
            broken.append({"url": src, "status": r["status"]})
    for im in first["images"][:15]:
        if im["src"] and not im["src"].startswith("data:"):
            r = fetch(urljoin(base + "/", im["src"]), method="HEAD")
            cl = int(r.get("headers", {}).get("content-length") or 0)
            if r.get("status") and r["status"] >= 400:
                broken.append({"url": im["src"], "status": r["status"]})
            elif cl > 300_000:
                R.setdefault("large_images", []).append({"src": im["src"], "kb": cl // 1024})
    R["js_bundles"] = {"first_party_total_kb_compressed": round(total / 1024, 1), "count": len(bundles),
                       "largest": sorted(bundles, key=lambda b: -b["kb_compressed"])[:8]}
    R["sourcemaps"] = {"publicly_served": maps[:10]}
    R["bundle_secret_hits"] = secret_hits
    R["broken_assets"] = broken

    # error leak probe
    er = fetch(f"{base}/api/__probe_{uuid.uuid4().hex[:6]}?id=%27%22")
    R["error_leak"] = {"status": er.get("status"), "stack_trace": bool(re.search(r"(at \w+ \(|Traceback|node_modules/|\.js:\d+:\d+|PrismaClient|SQLSTATE|ECONNREFUSED)", er.get("body") or ""))}

    years = re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d)", first["_body"], re.I)
    R["copyright_year"] = max(years) if years else None

    for pg in pages:
        for k in ("_internal", "_scripts", "_styles", "_body"):
            pg.pop(k, None)
    R["pages_crawled"] = len(pages)
    R["pages"] = pages
    print(json.dumps(R, indent=1))


if __name__ == "__main__":
    main()
