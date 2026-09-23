"""Load configuration, scan sources, filter and score postings, merge them into the state."""
import hashlib
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .extract import from_feed, from_html, page_text, page_urls, soup_of
from .fetch import Fetcher
from .text import Terms, clean, find_country, find_deadline, norm

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("position", "school", "group")
WATCH_EXTRA = ["position", "vacanc", "opening", "open call", "call for", "application", "apply", "deadline",
               "admission", "scholarship", "fellowship", "funded", "stelle", "ausschreibung", "bewerbung",
               "poste", "offre", "bando", "concorso", "posizion", "ammission", "stilling", "tjänst",
               "vacature", "candidat", "recruit"]


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


class Config:
    def __init__(self, root=ROOT):
        prof = yaml.safe_load((root / "profiles.yaml").read_text(encoding="utf-8"))
        srcs = yaml.safe_load((root / "sources.yaml").read_text(encoding="utf-8"))
        self.defaults = srcs.get("defaults") or {}
        self.sources = []
        for s in srcs.get("sources") or []:
            s = {**self.defaults, **s}
            if s.get("enabled", True) is False:
                continue
            for req in ("name", "url"):
                if not s.get(req):
                    raise ValueError(f"source without '{req}': {s}")
            s.setdefault("type", "html")
            s.setdefault("kind", "position")
            if s["kind"] not in KINDS:
                raise ValueError(f"{s['name']}: kind must be one of {KINDS}")
            f = s.get("filter", ["phd", "math"])
            s["filter"] = [f] if isinstance(f, str) else list(f or [])
            self.sources.append(s)
        names = [s["name"] for s in self.sources]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"duplicate source names: {dup}")

        self.profiles = {}
        for pid, p in prof["profiles"].items():
            kw = {norm(k): (k, int(w)) for k, w in (p.get("keywords") or {}).items()}
            rw = int(p.get("researcher_weight", 8))
            for r in p.get("researchers") or []:
                kw[norm(r)] = (r, rw)
            self.profiles[pid] = {
                "name": p.get("name", pid),
                "kw": kw,
                "rx": {n: re.compile(r"(?<![a-z0-9])" + re.escape(n)) for n in kw},
            }
        self.phd = Terms(prof.get("phd_terms") or [])
        self.math = Terms(prof.get("math_terms") or [])
        self.phd_body = Terms(prof.get("phd_body_terms") or [])
        self.exclude = Terms(prof.get("exclude_title_terms") or [])
        self.hard_exclude = Terms(prof.get("hard_exclude_title_terms") or [])
        self.watch_terms = Terms(list(prof.get("phd_terms") or []) + WATCH_EXTRA)

    def math_count(self, text_n):
        return sum(len(rx.findall(text_n)) for rx in self.math.rx.values())

    def score(self, title_n, text_n):
        scores, matched = {}, {}
        for pid, p in self.profiles.items():
            total, hits = 0, []
            for n, rx in p["rx"].items():
                label, w = p["kw"][n]
                if rx.search(title_n):
                    total += 2 * w
                    hits.append(label)
                elif rx.search(text_n):
                    total += w
                    hits.append(label)
            scores[pid] = total
            matched[pid] = sorted(hits, key=lambda h: -p["kw"][norm(h)][1])[:10]
        return scores, matched

    def passes(self, filters, title_n, ctx_n, body_n=None, scores=None):
        """ctx_n: title + listing text; body_n: full posting text when it was fetched."""
        if self.hard_exclude.any(title_n) and not re.search(r"phd (?:or|and|/) post ?doc", title_n):
            return False
        if self.exclude.any(title_n) and not self.phd.any(title_n):
            return False
        if "phd" in filters and not (self.phd.any(ctx_n) or (body_n and self.phd_body.any(body_n))):
            return False
        if "math" in filters and not (self.math.any(ctx_n) or (body_n and self.math_count(body_n) >= 3)):
            return False
        if "topic" in filters and scores is not None and not any(scores.values()):
            return False
        return True


def _snippet(cfg, lines, fallback, limit=420):
    """Most informative sentences: ones naming a keyword or a doctoral term."""
    picked, size = [], 0
    for ln in lines:
        n = norm(ln)
        if len(ln) < 25:
            continue
        hit = any(rx.search(n) for p in cfg.profiles.values() for rx in p["rx"].values()) or cfg.phd.any(n)
        if hit:
            picked.append(ln[:260])
            size += len(ln)
            if size > limit:
                break
    return (" … ".join(picked) or fallback)[:limit + 200]


def scan_listing(src, cfg, fetcher, known, rejected, only_new=True):
    """Candidates from a listing source; returns (raw_count, [posting], [seen_known_ids], [rejected_ids])."""
    raw = []
    for u in page_urls(src):
        text = fetcher.get(u, delay=src.get("delay"))
        raw += from_feed(text, u) if src["type"] == "rss" else from_html(text, u, src)
    seen_known, out, dropped, details_left = [], [], [], int(src.get("max_details", 20))
    uniq = {}
    for it in raw:
        uniq.setdefault(it["url"], it)
    listing_filter = src.get("listing_filter")
    if listing_filter is None:
        listing_filter = [f for f in src["filter"] if f == "phd"] if src.get("details") else src["filter"]
    for it in uniq.values():
        pid = sha(it["url"])
        if pid in known and only_new:
            seen_known.append(pid)
            continue
        if pid in rejected and only_new:
            continue
        title_n, ctx_n = norm(it["title"]), norm(it["context"])
        if not cfg.passes([f for f in listing_filter if f != "topic"], title_n, norm(it["title"] + " " + it["context"])):
            continue  # cheap to re-check, so not remembered
        body, lines = it["context"], [it["context"]]
        detailed = False
        if src.get("details"):
            if details_left <= 0:
                continue  # picked up on a later run
            details_left -= 1
            try:
                html = fetcher.get(it["url"], delay=src.get("delay"))
            except Exception:
                html = None
            if html is not None:
                if len(html) < 3000 and re.search(r"http-equiv=[\"']?refresh", html, re.I):
                    dropped.append(pid)
                    continue  # withdrawn posting that redirects elsewhere
                lines = page_text(html, src.get("detail_selector"))
                body = " ".join(lines)[:40000]
                detailed = True
                if it.get("slug") or src.get("title_from_page"):
                    h1 = soup_of(html).find("h1")
                    if h1 and len(clean(h1.get_text(" "))) > 5:
                        it["title"] = clean(h1.get_text(" "))[:300]
                        title_n = norm(it["title"])
        text_n = norm(it["title"] + " " + body)
        scores, matched = cfg.score(title_n, text_n)
        is_math = cfg.math.any(norm(it["title"] + " " + it["context"])) or cfg.math_count(text_n) >= 3
        deadline = find_deadline(it["context"]) or find_deadline(body)
        country = find_country(it["title"] + " " + it["context"]) or find_country(body[:3000])
        ctx_n = norm(it["title"] + " " + it["context"])
        if not cfg.passes(src["filter"], title_n, ctx_n, text_n if detailed else None, scores) or (
                deadline and deadline < date.today().isoformat()) or (
                src.get("europe_only") and not country):
            if detailed:
                dropped.append(pid)  # remember, so its page is not fetched again
            continue
        ctx_rest = clean(it["context"].replace(it["title"], "", 1))
        out.append({
            "id": pid, "url": it["url"], "title": it["title"] or it["url"], "source": src["name"],
            "kind": src["kind"],
            "country": country or src.get("country") or "",
            "deadline": deadline,
            "snippet": _snippet(cfg, lines, ctx_rest[:420]) if detailed else ctx_rest[:420],
            "scores": scores, "matched": matched, "detailed": detailed, "math": is_math,
        })
    return len(uniq), out, seen_known, dropped


def scan_watch(src, cfg, fetcher, prev):
    """A watched page: returns (lines_count, posting, new_watch_state)."""
    lines = page_text(fetcher.get(src["url"], delay=src.get("delay")), src.get("selector"))
    interesting = [ln for ln in lines if cfg.watch_terms.any(norm(ln))][:400]
    h = sha("\n".join(interesting))
    added = []
    if prev and prev.get("hash") != h:
        old = set(prev.get("lines") or [])
        added = [ln for ln in interesting if ln not in old]
    text = " ".join(interesting)
    scores, matched = cfg.score(norm(src["name"]), norm(text))
    posting = {
        "id": sha("watch:" + src["url"]), "url": src["url"], "title": src["name"], "source": src["name"],
        "kind": src["kind"], "country": src.get("country") or find_country(src["name"] + " " + text) or "",
        "deadline": find_deadline(text), "scores": scores, "matched": matched, "watch": True,
        "changes": added[:15],
        "snippet": " … ".join(ln[:200] for ln in interesting[:6])[:600],
    }
    return len(lines), posting, {"hash": h, "lines": interesting}


def run_source(src, cfg, fetcher, state, only_new=True):
    if src["type"] == "watch":
        prev = state["watch"].get(src["url"])
        n, posting, wstate = scan_watch(src, cfg, fetcher, prev)
        return {"found": n, "items": [posting], "seen": [], "watch": {src["url"]: wstate},
                "changed": bool(posting["changes"]) or prev is None}
    n, items, seen, dropped = scan_listing(src, cfg, fetcher, set(state["postings"]),
                                           set(state.get("rejected", {})), only_new)
    return {"found": n, "items": items, "seen": seen, "watch": {}, "rejected": dropped}


def empty_state():
    return {"version": 1, "generated": None, "profiles": {}, "postings": {}, "sources": {}, "watch": {},
            "rejected": {}}


def scan(cfg, state, only=None, workers=8, log=print):
    """Scan every source (or those whose name contains `only`) and merge into state in place."""
    fetcher = Fetcher()
    ts = now_iso()
    srcs = [s for s in cfg.sources if not only or only.lower() in s["name"].lower()]
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(run_source, s, cfg, fetcher, state): s for s in srcs}
        for fut in as_completed(futs):
            s = futs[fut]
            try:
                results[s["name"]] = fut.result()
                r = results[s["name"]]
                log(f"  ok   {s['name']}: {r['found']} found, {len(r['items'])} new/updated")
            except Exception as e:
                results[s["name"]] = {"error": f"{type(e).__name__}: {e}"[:300]}
                log(f"  FAIL {s['name']}: {results[s['name']]['error']}")
                if log is print and not isinstance(e, RuntimeError):
                    traceback.print_exc()

    for s in srcs:
        r = results[s["name"]]
        h = state["sources"].setdefault(s["name"], {})
        h.update({"url": s["url"] if isinstance(s["url"], str) else s["url"][0], "type": s["type"],
                  "kind": s["kind"], "country": s.get("country", ""), "last_run": ts})
        if "error" in r:
            h.update({"ok": False, "error": r["error"], "fails": h.get("fails", 0) + 1})
            continue
        h.update({"ok": True, "error": None, "fails": 0, "last_ok": ts, "found": r["found"]})
        state["watch"].update(r["watch"])
        for pid in r.get("rejected", []):
            state.setdefault("rejected", {})[pid] = ts
        for pid in r["seen"]:
            state["postings"][pid]["last_seen"] = ts
        for p in r["items"]:
            old = state["postings"].get(p["id"])
            if p.get("watch"):
                changed = r["changed"] and old is not None
                p["first_seen"] = old["first_seen"] if old else ts
                p["updated"] = ts if (changed or not old) else old.get("updated", ts)
                p["changes"] = p["changes"] if changed else (old or {}).get("changes", [])
                p["changed_at"] = ts if changed else (old or {}).get("changed_at")
            else:
                p["first_seen"] = old["first_seen"] if old else ts
                p["updated"] = old.get("updated", ts) if old else ts
            p["last_seen"] = ts
            state["postings"][p["id"]] = p
        h["kept"] = sum(1 for p in state["postings"].values() if p["source"] == s["name"])

    prune(state)
    state["generated"] = ts
    state["profiles"] = {pid: {"name": p["name"]} for pid, p in cfg.profiles.items()}
    return state


def prune(state, days_unseen=60):
    now = datetime.now(timezone.utc)
    keep = {}
    for pid, p in state["postings"].items():
        last = datetime.fromisoformat(p["last_seen"])
        if now - last > timedelta(days=days_unseen):
            continue
        if p.get("deadline") and not p.get("watch"):
            try:
                dl = datetime.fromisoformat(p["deadline"]).replace(tzinfo=timezone.utc)
                if now - dl > timedelta(days=45) and now - last > timedelta(days=3):
                    continue
            except ValueError:
                pass
        keep[pid] = p
    state["postings"] = keep
    state["rejected"] = {k: v for k, v in state.get("rejected", {}).items()
                         if now - datetime.fromisoformat(v) < timedelta(days=120)}
