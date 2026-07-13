# /// script
# requires-python = ">=3.11"
# dependencies = ["chess"]
# ///
"""Generate line-trainer decks from the canonical opening database.

Builds one deck per opening family (the part of the name before ":") in
lichess-org/chess-openings. Walk of the family's union trie:

  - drilled side to move: answer = the canonical move carried by the most
    named variations; one card per position, then follow that move only
    (it's a repertoire).
  - opponent to move: branch into every canonical reply.

The drilled side is whoever made the last move of the family's root entry
(the entry named exactly the family): Sicilian Defense -> Black,
Ruy Lopez -> White. Override with --side.

Usage:
  uv run scripts/opening-deck.py --tsv-dir <chess-openings clone> --dry
  uv run scripts/opening-deck.py --tsv-dir ... --opening "Sicilian Defense"
  uv run scripts/opening-deck.py --tsv-dir ... --all --min-cards 20
"""

import argparse
import io
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

import chess
import chess.pgn

REPO = Path(__file__).resolve().parent.parent


def new_node():
    return dict(children={}, name=None, eco=None, weight=0, last=None)


def load_entries(tsv_dir):
    entries = []
    for f in sorted(Path(tsv_dir).glob("[a-e].tsv")):
        for line in f.read_text().splitlines()[1:]:
            eco, name, pgn = line.split("\t")
            entries.append((eco, name, pgn))
    return entries


def family_of(name):
    return name.split(":")[0].split(",")[0].strip()


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


def build_trie(entries, family):
    trie = new_node()
    root_entry = None
    for eco, name, pgn in entries:
        if family_of(name) != family:
            continue
        game = chess.pgn.read_game(io.StringIO(pgn))
        node, board, last = trie, chess.Board(), None
        node["weight"] += 1
        for mv in game.mainline_moves():
            san = board.san(mv)
            node = node["children"].setdefault(san, new_node())
            node["weight"] += 1
            board.push(mv)
            last = mv
        node["name"], node["eco"], node["last"] = name, eco, last
        exact = name == family
        if root_entry is None or (exact and not root_entry[3]) or (
                exact == root_entry[3] and len(pgn) < len(root_entry[2])):
            root_entry = (eco, name, pgn, exact)
    return trie, root_entry


def detect_side(family, root_entry):
    # The name usually says whose opening it is; root-entry parity (who made
    # the defining line's last move) settles keyword-free names (Ruy Lopez).
    if re.search(r"Defense|Declined|Accepted|Countergambit", family):
        return chess.BLACK
    if re.search(r"Opening|Game|Attack|System", family):
        return chess.WHITE
    if root_entry is None:
        return None
    game = chess.pgn.read_game(io.StringIO(root_entry[2]))
    board = game.end().board()
    return chess.BLACK if board.turn == chess.WHITE else chess.WHITE


def gen_deck(entries, family, side_override=None):
    trie, root_entry = build_trie(entries, family)
    side = (chess.WHITE if side_override == "white" else
            chess.BLACK if side_override == "black" else
            detect_side(family, root_entry))
    if side is None:
        return None
    side_name = "White" if side == chess.WHITE else "Black"
    strip = lambda n: n.replace(f"{family}: ", "").replace(family, "main line")

    cards, visited = [], set()

    def pos_key(board):
        p = board.fen().split()
        return (p[0], p[1], p[2])

    def walk(node, board, sans, opening):
        if board.turn == side:
            if not node["children"]:
                return
            bsan, child = max(node["children"].items(),
                              key=lambda kv: kv[1]["weight"])
            pk = pos_key(board)
            if pk in visited:
                return
            visited.add(pk)
            move = board.parse_san(bsan)
            replies = []
            movenum = len(sans) // 2 + 2 - (0 if side == chess.BLACK else 1)
            for wsan, gc in sorted(child["children"].items(),
                                   key=lambda kv: -kv[1]["weight"]):
                label = f"{movenum}. {wsan}"
                if side == chess.WHITE:
                    label = f"{movenum}... {wsan}"
                if gc["name"]:
                    label += f" ({strip(gc['name'])})"
                replies.append(label)
            extra = f"Line: {movetext(sans + [bsan], bold_last=True)}."
            if child["name"]:
                extra += f" This is the {strip(child['name'])} ({child['eco']})."
            if replies:
                extra += " Covered replies: " + ", ".join(replies) + "."
            opp_path = [s for i, s in enumerate(sans)
                        if (i % 2 == 0) == (side == chess.BLACK)]
            key = ("l-" + "-".join(slug_san(s) for s in opp_path)
                   if opp_path else "l-root")
            cards.append(dict(
                key=key, model="chess",
                fields=dict(
                    fen=board.fen(),
                    answer=re.sub(r"[+#]", "", bsan),
                    answerUci=move.uci(),
                    orientation=side_name.lower(),
                    lastMove=board.move_stack[-1].uci() if board.move_stack else None,
                    prompt=f"You are {side_name} in the "
                           f"{strip(opening) if opening else family}. "
                           f"What is the book move?",
                    extra=extra,
                ),
                tags=["chess::line"],
            ))
            if cards[-1]["fields"]["lastMove"] is None:
                del cards[-1]["fields"]["lastMove"]
            board.push(move)
            walk(child, board, sans + [bsan], child["name"] or opening)
            board.pop()
        else:
            for wsan, child in sorted(node["children"].items(),
                                      key=lambda kv: -kv[1]["weight"]):
                move = board.parse_san(wsan)
                board.push(move)
                walk(child, board, sans + [wsan], child["name"] or opening)
                board.pop()

    walk(trie, chess.Board(), [], family)
    if not cards:
        return None

    game = chess.pgn.read_game(io.StringIO(root_entry[2]))
    cover_board = game.end().board()
    cover_fen = quote(cover_board.fen(), safe="")
    last = list(game.mainline_moves())[-1]
    cover = (f"https://lichess1.org/export/fen.gif?fen={cover_fen}"
             f"&color={side_name.lower()}&theme=brown&piece=cburnett"
             f"&lastMove={last.uci()}")

    n_vars = trie["weight"]
    return side_name, dict(
        key=slugify(family),
        version=1,
        name=f"The {family}" if not family.startswith(("The ", "A ")) else family,
        description=(
            f"Line trainer for the {family}, generated from the canonical "
            f"opening database (lichess-org/chess-openings): {len(cards)} "
            f"positions drilled book-move by book-move from {side_name}'s "
            f"side across {n_vars} named variations. Each card shows the "
            f"position from {side_name}'s side and asks for the book move; "
            f"the back gives the line so far, the variation name and ECO "
            f"code, and the covered replies that continue it."),
        category="Chess",
        topics=["chess", "openings", slugify(family)],
        coverImage=cover,
        ttsLang=None,
        notes=cards,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv-dir", required=True)
    ap.add_argument("--opening")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--side", choices=["white", "black"])
    ap.add_argument("--min-cards", type=int, default=20)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    entries = load_entries(args.tsv_dir)
    families = sorted({family_of(n) for _, n, _ in entries})
    targets = [args.opening] if args.opening else families
    if not args.opening and not args.all and not args.dry:
        ap.error("pass --opening NAME, --all, or --dry")

    covered = []
    for p in (REPO / "decks").glob("*.json"):
        covered.append(json.loads(p.read_text())["name"])

    rows, written = [], 0
    for fam in targets:
        res = gen_deck(entries, fam, args.side if args.opening else None)
        if res is None:
            continue
        side, deck = res
        n = len(deck["notes"])
        keep = n >= args.min_cards or bool(args.opening)
        path = REPO / "decks" / f"{deck['key']}.json"
        exists = path.exists() or any(fam in name for name in covered)
        rows.append((n, fam, side, "skip:exists" if exists else
                     ("write" if keep else "skip:small")))
        if args.dry or not keep or exists:
            continue
        path.write_text(json.dumps(deck, indent=2) + "\n")
        written += 1

    for n, fam, side, action in sorted(rows, reverse=True):
        print(f"{n:4d} cards  {side:5s}  {action:11s}  {fam}")
    print(f"\n{written} deck(s) written. Run: node scripts/build.mjs")


if __name__ == "__main__":
    main()
