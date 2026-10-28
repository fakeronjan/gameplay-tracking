"""One-time build of the Switch screenshot galleries (local only; inputs are the archive).

Each game gets up to 24 screenshots: its screenshots are split into 24 equal stretches
by date and one is picked at random from each, so a sample spans the whole time the game
was played. The pick is seeded per game, so rebuilding gives the same sample.

Writes 320px thumbnails and 960px views as webp, plus gallery.json, into the
gameplay-screenshots repo next to this one (published at fakeronjan.github.io/gameplay-screenshots).

    python build_gallery.py
"""

import json
import random
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
ARCHIVE = Path.home() / "Documents/Archive/Nintendo/Nintendo Switch Screenshots"
OUT = HERE.parent / "gameplay-screenshots" / "docs"
PER_GAME = 24
SIZES = {"t": 320, "f": 960}


def main():
    names = json.loads((HERE / "config" / "switch_game_names.json").read_text())
    overrides = json.loads((HERE / "config" / "switch_overrides.json").read_text())["file_overrides"]

    shots = defaultdict(list)  # first screenshot game id of the row -> [(stamp, file)]
    for f in sorted(ARCHIVE.rglob("*.jpg")):
        m = re.fullmatch(r"(\d{14})\d\d-([0-9A-F]{32})\.jpg", f.name)
        if not m:
            continue
        game_id = overrides.get(f.name, {}).get("game_id", m.group(2))
        if names[game_id].get("exclude"):
            continue
        shots[game_id].append((m.group(1), f))

    # One gallery per page row: games with two screenshot ids (Puyo Puyo Tetris JP + US) share one
    row_of = {}
    for gid, info in names.items():
        row_of[gid] = info.get("display") or info["name"]
    by_row = defaultdict(list)
    for gid, items in shots.items():
        by_row[row_of[gid]] += items
    first_id = {}
    for gid in sorted(shots):
        first_id.setdefault(row_of[gid], gid)

    gallery = {}
    for row, items in sorted(by_row.items()):
        items.sort()
        if len(items) > PER_GAME:
            rng = random.Random(f"gameplay-tracking:{row}")
            items = [rng.choice(items[i * len(items) // PER_GAME:(i + 1) * len(items) // PER_GAME])
                     for i in range(PER_GAME)]
        entries = []
        for stamp, f in items:
            name = f"{stamp}-{f.stem[-32:-24].lower()}.webp"
            for kind, size in SIZES.items():
                out = OUT / kind / name
                if not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    im = Image.open(f).convert("RGB")
                    im.thumbnail((size, size))
                    im.save(out, "WEBP", quality=72 if kind == "t" else 80)
            entries.append({"time": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[8:10]}:{stamp[10:12]}:{stamp[12:14]}",
                            "img": name})
        gallery[f"switch:{first_id[row]}"] = {"game": row, "total": len(by_row[row]), "shots": entries}

    (OUT / "gallery.json").write_text(json.dumps(gallery, indent=1, ensure_ascii=False) + "\n")
    print(f"gallery: {len(gallery)} games, {sum(len(g['shots']) for g in gallery.values())} of "
          f"{sum(g['total'] for g in gallery.values())} screenshots")


if __name__ == "__main__":
    main()
