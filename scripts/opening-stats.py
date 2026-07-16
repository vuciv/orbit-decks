# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Build local opening frequency stats from a lichess database dump.

Streams decompressed PGN on stdin, keeps rated games in the requested
speeds and rating band, counts SAN-path frequencies for the first --plies
half-moves, and writes a pruned trie as JSON for opening-deck.py --stats.

The monthly dumps (database.lichess.org) are ~30 GB compressed, but zstd
streams and is partially decompressible: pipe the download straight
through pzstd and this script exits after --max-games, killing the
download with it. Nothing large lands on disk.

Usage:
  curl -s https://database.lichess.org/standard/lichess_db_standard_rated_2026-06.pgn.zst \
    | pzstd -dc \
    | uv run scripts/opening-stats.py --label 2026-06 --max-games 3000000
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMENT_RE = re.compile(r"\{[^}]*\}")
MOVENUM_RE = re.compile(r"^\d+\.+(.*)$")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


def parse_sans(text, plies):
    out = []
    for tok in COMMENT_RE.sub(" ", text).split():
        if tok in RESULTS:
            break
        if tok[0].isdigit():
            m = MOVENUM_RE.match(tok)
            if not m or not m.group(1):
                continue
            tok = m.group(1)
        if tok.startswith("$"):
            continue
        tok = tok.rstrip("?!")
        if not tok:
            continue
        out.append(tok)
        if len(out) >= plies:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "scripts" / "opening-stats.json"))
    ap.add_argument("--label", default="lichess database dump")
    ap.add_argument("--speeds", default="Blitz,Rapid,Classical")
    ap.add_argument("--min-rating", type=int, default=1600)
    ap.add_argument("--max-rating", type=int, default=2200)
    ap.add_argument("--plies", type=int, default=26)
    ap.add_argument("--max-games", type=int, default=3_000_000)
    ap.add_argument("--prune-every", type=int, default=250_000)
    ap.add_argument("--prune-min", type=int, default=4)
    ap.add_argument("--out-min", type=int, default=None,
                    help="drop trie nodes below this count in the output")
    args = ap.parse_args()
    speeds = tuple(s.strip() for s in args.speeds.split(","))

    root = {"n": 0, "c": {}}
    kept = 0

    def insert(sans):
        node = root
        node["n"] += 1
        for s in sans:
            node = node["c"].setdefault(s, {"n": 0, "c": {}})
            node["n"] += 1

    # Deep rare paths explode memory; periodically drop cold subtrees.
    # Slight undercount for lines near the threshold, which the deck
    # generator prunes anyway.
    def prune(node, floor, depth=0, min_depth=6):
        if depth >= min_depth:
            node["c"] = {s: ch for s, ch in node["c"].items()
                         if ch["n"] >= floor}
        for ch in node["c"].values():
            prune(ch, floor, depth + 1, min_depth)

    event_ok = accept = False
    welo = belo = None
    buf, buflen, in_moves = [], 0, False

    def rating_ok():
        if not (welo and belo and welo.isdigit() and belo.isdigit()):
            return False
        mean = (int(welo) + int(belo)) / 2
        return args.min_rating <= mean < args.max_rating

    def finish():
        nonlocal kept
        if not (accept and buf):
            return
        sans = parse_sans(" ".join(buf), args.plies)
        if len(sans) < 2:
            return
        insert(sans)
        kept += 1
        if kept % 100_000 == 0:
            print(f"  {kept:,} games kept...", file=sys.stderr, flush=True)
        if kept % args.prune_every == 0:
            prune(root, args.prune_min)

    for raw in sys.stdin:
        if raw.startswith("["):
            if in_moves:
                finish()
                event_ok, accept, welo, belo = False, False, None, None
                buf, buflen, in_moves = [], 0, False
                if kept >= args.max_games:
                    break
            if raw.startswith("[Event "):
                event_ok = "Rated" in raw and any(s in raw for s in speeds)
            elif raw.startswith("[WhiteElo "):
                welo = raw.split('"')[1]
            elif raw.startswith("[BlackElo "):
                belo = raw.split('"')[1]
        elif raw.strip():
            if not in_moves:
                in_moves = True
                accept = event_ok and rating_ok()
            if accept and buflen < 6000:
                buf.append(raw.strip())
                buflen += len(raw)
    else:
        finish()

    out_min = args.out_min or max(50, kept // 60_000)
    prune(root, out_min, min_depth=1)
    blob = dict(
        meta=dict(label=args.label, speeds=args.speeds,
                  ratings=f"{args.min_rating}-{args.max_rating}",
                  games=kept, plies=args.plies),
        trie=root,
    )
    Path(args.out).write_text(json.dumps(blob, separators=(",", ":")))
    size = Path(args.out).stat().st_size
    print(f"{kept:,} games -> {args.out} ({size / 1e6:.1f} MB)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
