"""Turn a fetched page or feed into candidate postings."""
import re
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import feedparser
from bs4 import BeautifulSoup

from .text import clean

NOISE_TAGS = ["script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "iframe"]
BLOCKS = ["li", "tr", "article", "section", "div", "p", "dd", "td"]


def soup_of(html):
    s = BeautifulSoup(html, "lxml")
    for t in s(["script", "style", "noscript", "svg", "iframe"]):
        t.decompose()
    return s


def page_urls(src):
    """All listing URLs of a source, including pagination."""
    urls = src["url"] if isinstance(src["url"], list) else [src["url"]]
    pages = int(src.get("pages", 1))
    param = src.get("page_param", "page")
    start = int(src.get("page_start", 0))
    out = []
    for u in urls:
        out.append(u)
        for i in range(1, pages):
            p = urlparse(u)
            q = dict(parse_qsl(p.query, keep_blank_values=True))
            q[param] = str(start + i)
            out.append(urlunparse(p._replace(query=urlencode(q))))
    return out


def from_feed(text, base):
    f = feedparser.parse(text)
    items = []
    for e in f.entries:
        link = e.get("link") or ""
        summary = BeautifulSoup(e.get("summary", "") or "", "lxml").get_text(" ")
        items.append({"url": urljoin(base, link), "title": clean(e.get("title", "")),
                      "context": clean(e.get("title", "") + " " + summary)})
    return items


def _context(a, limit=1200):
    """Text of the smallest enclosing block that says more than the link itself."""
    own = len(a.get_text(" ", strip=True))
    node, best = a, a
    while node.parent is not None and node.parent.name not in ("body", "html", "[document]"):
        node = node.parent
        n = len(node.get_text(" ", strip=True))
        if n > limit:
            break
        best = node
        if node.name in BLOCKS and n > own + 40:
            break
    return clean(best.get_text(" ", strip=True))[:limit]


def slug_title(url):
    """Readable title guessed from the last meaningful path segment of a URL."""
    parts = [p for p in urlparse(url).path.split("/") if p and not p.isdigit()]
    return clean(re.sub(r"[-_+]+", " ", unquote(parts[-1] if parts else url))).capitalize()


def from_raw(html, base, src):
    """Every URL in the raw page text that matches link_pattern (for sitemaps and JavaScript-built pages)."""
    rx = re.compile(src["link_pattern"])
    items = []
    for m in re.finditer(r"""(?:https?://|/)[^\s"'<>\\]+""", html.replace("\\/", "/")):
        u = urljoin(base, m.group(0))
        if rx.search(u):
            items.append({"url": u, "title": slug_title(u), "context": slug_title(u), "slug": True})
    return items


def from_html(html, base, src):
    if src.get("links") == "raw":
        items = from_raw(html, base, src)
        return _dedupe(items, base, None)
    s = soup_of(html)
    link_rx = re.compile(src["link_pattern"]) if src.get("link_pattern") else None
    items = []
    if src.get("item"):
        for it in s.select(src["item"]):
            a = it.select_one(src["link"]) if src.get("link") else it.find("a", href=True)
            if a is None or not a.get("href"):
                continue
            title_el = it.select_one(src["title"]) if src.get("title") else a
            items.append({"url": urljoin(base, a["href"]),
                          "title": clean(title_el.get_text(" ", strip=True)),
                          "context": clean(it.get_text(" ", strip=True))[:1500]})
    else:
        root = s.select_one(src["scope"]) if src.get("scope") else s
        for t in (root or s)(NOISE_TAGS):
            t.decompose()
        for a in (root or s).find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "javascript:", "tel:")):
                continue
            title = clean(a.get_text(" ", strip=True))
            if len(title) < 8:
                continue
            items.append({"url": urljoin(base, href), "title": title[:300], "context": _context(a)})
    return _dedupe(items, base, link_rx)


def _dedupe(items, base, link_rx):
    out, seen = [], set()
    for it in items:
        u = it["url"].split("#")[0]
        if link_rx and not link_rx.search(u):
            continue
        if u in seen or u.rstrip("/") == base.rstrip("/"):
            continue
        seen.add(u)
        it["url"] = u
        out.append(it)
    return out


def page_text(html, selector=None):
    """Readable text of a page, one line per block, without navigation chrome."""
    s = soup_of(html)
    root = (s.select_one(selector) if selector else None) or s.find("main") or s.find(
        attrs={"role": "main"}) or s.find("article") or s.body or s
    for t in root(NOISE_TAGS):
        t.decompose()
    for br in root.find_all("br"):
        br.replace_with("\n")
    lines = []
    for block in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "td", "dt", "dd", "div"]):
        if block.find(["p", "li", "div", "td", "h1", "h2", "h3", "h4"]):
            continue  # only leaf blocks, to avoid duplicates
        for ln in block.get_text(" ").split("\n"):
            ln = clean(ln)
            if ln:
                lines.append(ln)
    if not lines:
        lines = [clean(x) for x in root.get_text("\n").split("\n") if clean(x)]
    out, prev = [], None
    for ln in lines:
        if ln != prev:
            out.append(ln)
        prev = ln
    return out
