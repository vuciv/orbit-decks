# /// script
# requires-python = ">=3.11"
# dependencies = ["chess", "requests"]
# ///
"""Generate one repertoire deck per opening family from real game frequencies.

Deck = one opening family x one color x one committed repertoire.

  - Spine: the family's defining moves (its root entry in
    lichess-org/chess-openings) are forced for both sides. "The Italian
    Game as White" starts branching only once the Italian is on the board;
    1...c5 is some other deck's job.
  - Your side: exactly ONE move per position. Named lines constrain the
    choice while inside the family's book; the most played move in the
    Lichess opening explorer decides among candidates and beyond the book.
  - Opponent side: branch into replies by actual play frequency, most
    common first, until they cover --cover of games; replies below
    --min-reply and positions seen fewer than --min-games times are
    pruned. Depth therefore tracks how often lines actually occur.

Split where YOU choose, merge where the OPPONENT chooses: an alternative
repertoire against the same opening is a separate deck (--via "Najdorf"),
opponent replies are branches inside one deck.

Regenerating an existing deck file (--force) preserves notes that are not
line cards (idea cards, anything not tagged chess::line), keeps stable
keys for unchanged lines so review progress survives, and bumps version.

Frequencies come from --stats (a local table built by opening-stats.py
from the CC0 lichess database dumps; fully offline) or, without --stats,
from the Lichess opening explorer API (responses cached in
~/.cache/orbit-opening-explorer).

Usage:
  uv run scripts/opening-deck.py --tsv-dir <chess-openings clone> \
    --stats scripts/opening-stats.json --opening "Italian Game"
  uv run scripts/opening-deck.py --tsv-dir ... --stats ... --opening "Sicilian Defense" --via "Najdorf"
  uv run scripts/opening-deck.py --tsv-dir ... --stats ... --opening "Ruy Lopez" --dry
"""

import argparse
import hashlib
import io
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

import chess
import chess.pgn
import requests

REPO = Path(__file__).resolve().parent.parent
EXPLORER = "https://explorer.lichess.org"
UA = "orbit-packs opening-deck (https://github.com/vuciv/orbit-decks)"


def load_entries(tsv_dir):
    entries = []
    for f in sorted(Path(tsv_dir).glob("[a-e].tsv")):
        for line in f.read_text().splitlines()[1:]:
            eco, name, pgn = line.split("\t")
            entries.append((eco, name, pgn))
    return entries


def family_of(name):
    return name.split(":")[0].split(",")[0].strip()


def sub_of(name):
    if ":" not in name:
        return None
    return name.split(":", 1)[1].split(",")[0].strip()


def short_name(name):
    return name.split(":")[-1].split(",")[-1].strip()


def slugify(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def slug_san(san):
    return re.sub(r"[^a-z0-9]", "",
                  san.replace("O-O-O", "ooo").replace("O-O", "oo").lower())


def movetext(sans, bold_last=False):
    out = []
    for i, s in enumerate(sans):
        t = f"**{s}**" if bold_last and i == len(sans) - 1 else s
        out.append(f"{i // 2 + 1}. {t}" if i % 2 == 0 else t)
    return " ".join(out)


def pos_key(board):
    p = board.fen().split()
    return " ".join(p[:3])


def sans_of(pgn):
    game = chess.pgn.read_game(io.StringIO(pgn))
    board, sans = chess.Board(), []
    for mv in game.mainline_moves():
        sans.append(board.san(mv))
        board.push(mv)
    return sans, board


def new_node():
    return dict(children={}, name=None, eco=None)


def build_family(entries, family):
    trie, root_entry, names = new_node(), None, {}
    for eco, name, pgn in entries:
        if family_of(name) != family:
            continue
        node, board = trie, chess.Board()
        game = chess.pgn.read_game(io.StringIO(pgn))
        for mv in game.mainline_moves():
            san = board.san(mv)
            node = node["children"].setdefault(san, new_node())
            board.push(mv)
        node["name"], node["eco"] = name, eco
        names.setdefault(pos_key(board), (name, eco))
        exact = name == family
        if root_entry is None or (exact and not root_entry[3]) or (
                exact == root_entry[3] and len(pgn) < len(root_entry[2])):
            root_entry = (eco, name, pgn, exact)
    return trie, root_entry, names


def detect_side(family, root_entry):
    # The name usually says whose opening it is; root-entry parity (who made
    # the defining line's last move) settles keyword-free names (Ruy Lopez).
    if re.search(r"Defense|Declined|Accepted|Countergambit", family):
        return chess.BLACK
    if re.search(r"Opening|Game|Attack|System", family):
        return chess.WHITE
    if root_entry is None:
        return None
    _, board = sans_of(root_entry[2])
    return chess.BLACK if board.turn == chess.WHITE else chess.WHITE


class Explorer:
    def __init__(self, source, ratings, speeds, cache_dir, sleep):
        self.source, self.ratings, self.speeds = source, ratings, speeds
        self.sleep = sleep
        self.cache = Path(cache_dir).expanduser()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.calls = 0

    def stats(self, board):
        """Return (total games at this position, [{san, uci, games}] desc)."""
        tag = f"{self.source}|{self.ratings}|{self.speeds}|{board.epd()}"
        path = self.cache / (hashlib.sha1(tag.encode()).hexdigest() + ".json")
        if path.exists():
            data = json.loads(path.read_text())
        else:
            params = dict(variant="standard", fen=board.fen(),
                          moves=20, topGames=0, recentGames=0)
            if self.source == "lichess":
                params.update(speeds=self.speeds, ratings=self.ratings)
            while True:
                r = self.session.get(f"{EXPLORER}/{self.source}",
                                     params=params, timeout=30)
                if r.status_code == 429:
                    print("    explorer rate limit, waiting 60s...", flush=True)
                    time.sleep(60)
                    continue
                r.raise_for_status()
                break
            data = r.json()
            path.write_text(r.text)
            self.calls += 1
            if self.calls % 25 == 0:
                print(f"    {self.calls} explorer lookups...", flush=True)
            time.sleep(self.sleep)
        total = data["white"] + data["draws"] + data["black"]
        moves = [dict(san=m["san"], uci=m["uci"],
                      games=m["white"] + m["draws"] + m["black"])
                 for m in data["moves"]]
        moves.sort(key=lambda m: -m["games"])
        return total, moves

    def pool(self, root_total):
        volume = (f"{root_total / 1e6:.0f} million" if root_total >= 2e6
                  else f"{root_total:,}")
        if self.source == "masters":
            return f"{volume} master games"
        return (f"{volume} rated games "
                f"({self.ratings.replace(',', '/')} Lichess)")


class LocalStats:
    """Serves the same stats() as Explorer from opening-stats.py output."""

    def __init__(self, path):
        blob = json.loads(Path(path).read_text())
        self.meta = blob["meta"]
        self.calls = 0
        self.table = {}
        board = chess.Board()

        def index(node):
            row = self.table.setdefault(pos_key(board), {})
            for san, child in node["c"].items():
                try:
                    move = board.parse_san(san)
                except ValueError:
                    continue
                row[san] = row.get(san, 0) + child["n"]
                board.push(move)
                index(child)
                board.pop()

        index(blob["trie"])

    def stats(self, board):
        row = self.table.get(pos_key(board), {})
        total = sum(row.values())
        moves = []
        for san, games in sorted(row.items(), key=lambda kv: -kv[1]):
            try:
                uci = board.parse_san(san).uci()
            except ValueError:
                continue
            moves.append(dict(san=san, uci=uci, games=games))
        return total, moves

    def pool(self, root_total):
        m = self.meta
        return (f"{m['games']:,} rated games (Lichess database {m['label']}, "
                f"ratings {m['ratings']})")


def gen_deck(entries, family, explorer, opts, via=None, side_override=None):
    trie, root_entry, names = build_family(entries, family)
    if root_entry is None:
        return None
    side = (chess.WHITE if side_override == "white" else
            chess.BLACK if side_override == "black" else
            detect_side(family, root_entry))
    if side is None:
        return None
    side_name = "White" if side == chess.WHITE else "Black"
    opp_name = "Black" if side == chess.WHITE else "White"

    display = family
    spine, spine_end = sans_of(root_entry[2])
    if via:
        cands = [(len(p), n, p) for _, n, p in
                 [(e, n, p) for e, n, p in entries if family_of(n) == family]
                 if via.lower() in n.lower()]
        if not cands:
            raise SystemExit(f"--via {via!r}: no entry in {family} matches")
        _, via_name, via_pgn = min(cands)
        display = f"{family}: {sub_of(via_name) or short_name(via_name)}"
        spine, spine_end = sans_of(via_pgn)

    prompt = f"You are {side_name} in the {display}. What is the book move?"
    annotations = {}
    if opts.annotations:
        ann_path = Path(opts.annotations) / f"{slugify(display)}.json"
        if ann_path.exists():
            annotations = json.loads(ann_path.read_text())
    cards, visited = [], set()

    def walk(board, node, sans, prob, last_reply):
        total, moves = explorer.stats(board)
        if total < opts.min_games or len(sans) >= opts.max_plies:
            return
        games = {m["san"]: m["games"] for m in moves}
        on_spine = len(sans) < len(spine) and spine[:len(sans)] == sans

        if board.turn == side:
            if on_spine:
                choice = spine[len(sans)]
            elif node and node["children"]:
                choice = max(node["children"], key=lambda s: games.get(s, 0))
            elif moves:
                choice = moves[0]["san"]
            else:
                return
            pk = pos_key(board)
            if pk in visited:
                return
            visited.add(pk)
            move = board.parse_san(choice)
            board.push(move)
            named = names.get(pos_key(board))
            board.pop()
            extra = movetext(sans + [choice], bold_last=True)
            if named:
                extra += f" ({short_name(named[0])}, {named[1]})"
            why = annotations.get(pk)
            if why:
                extra += f". {why}"
            if last_reply:
                extra += (f" [{opp_name} plays {last_reply[0]} here "
                          f"{round(last_reply[1] * 100)}% of the time]")
            opp_path = [s for i, s in enumerate(sans)
                        if (i % 2 == 0) == (side == chess.BLACK)]
            key = ("l-" + "-".join(slug_san(s) for s in opp_path)
                   if opp_path else "l-root")
            fields = dict(
                fen=board.fen(),
                answer=re.sub(r"[+#]", "", choice),
                answerUci=move.uci(),
                orientation=side_name.lower(),
                prompt=prompt,
                extra=extra,
            )
            if board.move_stack:
                fields["lastMove"] = board.move_stack[-1].uci()
            cards.append(dict(depth=len(sans), prob=prob, key=key,
                              model="chess", fields=fields,
                              tags=["chess::line"]))
            board.push(move)
            walk(board, node["children"].get(choice) if node else None,
                 sans + [choice], prob, None)
            board.pop()
        else:
            replies, cum = [], 0.0
            if on_spine:
                san = spine[len(sans)]
                replies.append((san, games.get(san, 0) / total if total else 0))
            else:
                for m in moves:
                    share = m["games"] / total if total else 0
                    if cum >= opts.cover or share < opts.min_reply:
                        break
                    replies.append((m["san"], share))
                    cum += share
            for san, share in replies:
                move = board.parse_san(san)
                board.push(move)
                walk(board, node["children"].get(san) if node else None,
                     sans + [san], prob * share, (san, share))
                board.pop()

    walk(chess.Board(), trie, [], 1.0, None)
    if not cards:
        return None

    if len(cards) > opts.max_cards:
        cards.sort(key=lambda c: (-c["prob"], c["depth"], c["key"]))
        cards = cards[:opts.max_cards]
    cards.sort(key=lambda c: (c["depth"], -c["prob"], c["key"]))
    for c in cards:
        del c["depth"], c["prob"]

    cover_fen = quote(spine_end.fen(), safe="")
    last = spine_end.move_stack[-1].uci() if spine_end.move_stack else ""
    cover = (f"https://lichess1.org/export/fen.gif?fen={cover_fen}"
             f"&color={side_name.lower()}&theme=brown&piece=cburnett"
             f"&lastMove={last}")

    root_total, _ = explorer.stats(chess.Board())
    pool = explorer.pool(root_total)
    name = (f"The {family} as {side_name}" if display == family
            else f"{display} as {side_name}")
    return side_name, dict(
        key=slugify(display),
        version=1,
        name=name,
        description=(
            f"A {side_name} repertoire for the {display}, drilled one "
            f"position at a time: every card is a position with exactly one "
            f"book move to find. Built from {pool}: opponent replies "
            f"branch by how often they are "
            f"actually played, covering the most common "
            f"{round(opts.cover * 100)}% at each turn, so frequent lines "
            f"run deep and rare sidelines stay shallow. "
            f"{len(cards)} positions."),
        category="Chess",
        topics=["chess", "openings", slugify(family)],
        coverImage=cover,
        ttsLang=None,
        notes=cards,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv-dir", required=True)
    ap.add_argument("--opening", help='"Family" or "Family: Variation"')
    ap.add_argument("--opening-list",
                    help="file of openings, one per line, same syntax as --opening")
    ap.add_argument("--via", help="force the repertoire through this named variation")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--side", choices=["white", "black"])
    ap.add_argument("--stats", help="opening-stats.py JSON; offline, replaces the explorer API")
    ap.add_argument("--annotations", default=str(REPO / "scripts" / "annotations"),
                    help="dir of <deck-key>.json files mapping position keys to one-line whys, merged into extra")
    ap.add_argument("--source", choices=["lichess", "masters"], default="lichess")
    ap.add_argument("--ratings", default="1600,1800,2000,2200")
    ap.add_argument("--speeds", default="blitz,rapid,classical")
    ap.add_argument("--cover", type=float, default=0.9,
                    help="cumulative share of opponent replies to branch into")
    ap.add_argument("--min-reply", type=float, default=0.02,
                    help="drop opponent replies rarer than this share")
    ap.add_argument("--min-games", type=int, default=None,
                    help="stop lines once the position has fewer games (default: scaled to the corpus)")
    ap.add_argument("--max-plies", type=int, default=24)
    ap.add_argument("--max-cards", type=int, default=120,
                    help="keep the most frequently reached positions")
    ap.add_argument("--min-cards", type=int, default=12)
    ap.add_argument("--cache-dir", default="~/.cache/orbit-opening-explorer")
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--out-dir", default=str(REPO / "decks"))
    ap.add_argument("--force", action="store_true",
                    help="regenerate existing decks (preserves idea cards, bumps version)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not args.opening and not args.opening_list and not args.all:
        ap.error("pass --opening NAME, --opening-list FILE, or --all")

    entries = load_entries(args.tsv_dir)
    explorer = (LocalStats(args.stats) if args.stats else
                Explorer(args.source, args.ratings, args.speeds,
                         args.cache_dir, args.sleep))
    if args.min_games is None:
        root_total, _ = explorer.stats(chess.Board())
        args.min_games = max(25, round(root_total * 2e-6))
    out_dir = Path(args.out_dir)
    rows, written = [], 0

    def emit(family, via=None, forced=False):
        nonlocal written
        res = gen_deck(entries, family, explorer, args, via=via,
                       side_override=args.side if forced else None)
        if res is None:
            return
        side, deck = res
        label = deck["name"]
        path = out_dir / f"{deck['key']}.json"
        n = len(deck["notes"])
        if path.exists() and not args.force:
            action = "skip:exists"
        elif n < args.min_cards and not forced:
            action = "skip:small"
        else:
            action = "write"
            if path.exists():
                old = json.loads(path.read_text())
                kept = [x for x in old["notes"]
                        if x.get("model") != "chess"
                        or "chess::line" not in (x.get("tags") or [])]
                deck["notes"] = kept + deck["notes"]
                deck["version"] = old.get("version", 0) + 1
                action = f"update:v{deck['version']}"
            if not args.dry:
                path.write_text(json.dumps(deck, indent=2) + "\n")
                written += 1
            else:
                action = "dry:" + action
        rows.append((n, label, side, action))

    targets = []
    if args.opening:
        targets.append(args.opening)
    if args.opening_list:
        targets += [ln.strip() for ln in
                    Path(args.opening_list).read_text().splitlines()
                    if ln.strip()]
    if targets:
        for t in targets:
            family, via = t, args.via if t == args.opening else None
            if ":" in family and not via:
                family, via = [x.strip() for x in family.split(":", 1)]
            emit(family, via=via, forced=True)
    else:
        for fam in sorted({family_of(n) for _, n, _ in entries}):
            emit(fam)

    for n, label, side, action in sorted(rows, reverse=True):
        print(f"{n:4d} cards  {side:5s}  {action:14s}  {label}")
    print(f"\n{written} deck(s) written, {explorer.calls} explorer lookups. "
          f"Run: node scripts/build.mjs")


if __name__ == "__main__":
    main()
