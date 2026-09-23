"""Command line entry point.

  python -m radar run   --out _site [--state-url URL | --state-file PATH]   scan everything, write encrypted site
  python -m radar test  "part of a source name" [--all]                     try one source, print what it finds
  python -m radar check                                                     try every source, print a health table
"""
import argparse
import json
import os
import shutil
import sys
import time

import requests

from . import crypto
from .engine import ROOT, Config, empty_state, run_source, scan
from .fetch import Fetcher


def load_state(args, password):
    blob = None
    if args.state_file and os.path.exists(args.state_file):
        blob = open(args.state_file, "rb").read()
    elif args.state_url:
        r = requests.get(args.state_url, timeout=60, headers={"Cache-Control": "no-cache"})
        if r.status_code == 404:
            print("No published state yet: starting fresh.")
        else:
            r.raise_for_status()
            blob = r.content
    if blob is None:
        return empty_state()
    try:
        return crypto.decrypt(blob, password)
    except Exception:
        if os.environ.get("RADAR_RESET") == "1":
            print("Existing state could not be decrypted; RADAR_RESET=1 so starting fresh.")
            return empty_state()
        sys.exit("Existing data could not be decrypted with RADAR_PASSWORD. If you changed the password on "
                 "purpose, run the workflow once with the 'reset' option ticked.")


def cmd_run(args):
    password = os.environ.get("RADAR_PASSWORD")
    if not password:
        sys.exit("Set the RADAR_PASSWORD environment variable.")
    cfg = Config()
    state = load_state(args, password)
    if os.environ.get("RADAR_RESCAN") == "1":
        print("Forgetting previously rejected postings, so they are checked again.")
        state["rejected"] = {}
    print(f"Scanning {len(cfg.sources)} sources…")
    t0 = time.time()
    scan(cfg, state, only=args.only)
    failed = [n for n, h in state["sources"].items() if h.get("ok") is False]
    print(f"Done in {time.time() - t0:.0f}s: {len(state['postings'])} postings, {len(failed)} failing sources.")
    blob = crypto.encrypt(state, password)
    os.makedirs(args.out, exist_ok=True)
    open(os.path.join(args.out, "data.enc"), "wb").write(blob)
    for f in os.listdir(ROOT / "site"):
        shutil.copy(ROOT / "site" / f, args.out)
    if args.state_file:
        open(args.state_file, "wb").write(blob)
    if len(failed) > len(cfg.sources) / 2:
        sys.exit("More than half of the sources failed: check the network or the sources.")


def cmd_test(args):
    cfg = Config()
    srcs = [s for s in cfg.sources if args.name.lower() in s["name"].lower()]
    if not srcs:
        sys.exit(f"No source name contains '{args.name}'.")
    fetcher = Fetcher()
    for s in srcs:
        print(f"\n=== {s['name']}  [{s['type']}, {s['kind']}]")
        try:
            r = run_source(s, cfg, fetcher, empty_state())
        except Exception as e:
            print(f"   FAILED: {type(e).__name__}: {e}")
            continue
        print(f"   {r['found']} links/entries found, {len(r['items'])} kept after filters")
        items = sorted(r["items"], key=lambda p: -max(p["scores"].values() or [0]))
        for p in items[: (None if args.all else 15)]:
            sc = " ".join(f"{cfg.profiles[k]['name'][:3]}={v}" for k, v in p["scores"].items())
            print(f" - [{sc}] {p['title'][:110]}")
            print(f"     {p['url'][:120]}")
            print(f"     {p['country'] or '?'} | deadline {p['deadline'] or '?'} | "
                  f"{', '.join(sum(p['matched'].values(), []))[:100]}")
            if args.verbose:
                print("     " + p["snippet"][:300])


def cmd_check(args):
    cfg = Config()
    state = scan(cfg, empty_state(), only=args.only, log=lambda m: print(m, flush=True))
    rows = []
    for n, h in sorted(state["sources"].items()):
        kept = sum(1 for p in state["postings"].values() if p["source"] == n)
        rows.append({"name": n, "ok": h["ok"], "found": h.get("found"), "kept": kept, "error": h.get("error")})
    print()
    for r in rows:
        print(f"{'OK ' if r['ok'] else 'ERR'} {str(r['found'] or 0):>5} {r['kept']:>4}  {r['name']}"
              f"{'   ' + r['error'] if r['error'] else ''}")
    if args.json:
        json.dump(state, open(args.json, "w"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(prog="radar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--out", default="_site")
    p.add_argument("--state-url")
    p.add_argument("--state-file")
    p.add_argument("--only")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("test")
    p.add_argument("name")
    p.add_argument("--all", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_test)
    p = sub.add_parser("check")
    p.add_argument("--only")
    p.add_argument("--json")
    p.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
