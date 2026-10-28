"""Screenshot galleries for game pages, built locally from the archives (Switch, Miiverse,
PlayStation), plus PlayStation trophy "moments" for the Trophy Room.

Each game gets up to 24 screenshots: its screenshots are split into 24 equal stretches
by date and one is picked at random from each, so a sample spans the whole time the game
was played. The pick is seeded per game, so rebuilding gives the same sample.

Writes 320px thumbnails and 960px views as webp, plus gallery.json, into the
gameplay-screenshots repo next to this one (published at fakeronjan.github.io/gameplay-screenshots).

    python build_gallery.py
"""

import hashlib
import json
import random
import re
import subprocess
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
        m = re.fullmatch(r"(\d{14})\d\d-([0-9A-F]{32})L?\.jpg", f.name)  # Switch 2 adds "L"
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
            name = f"{stamp}-{f.stem.rstrip('L')[-32:-24].lower()}.webp"
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

    add_miiverse(gallery)
    moments = add_playstation(gallery)

    # Drop images no sample uses any more (a game's sample shifts when screenshots are added)
    keep = {s["img"] for g in gallery.values() for s in g["shots"]} | {m["img"] for m in moments.values()}
    stale = [p for kind in SIZES for p in (OUT / kind).glob("*.webp") if p.name not in keep]
    for p in stale:
        p.unlink()
    (OUT / "gallery.json").write_text(json.dumps(gallery, indent=1, ensure_ascii=False) + "\n")
    (OUT / "moments.json").write_text(json.dumps(moments, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"gallery: {len(gallery)} games, {sum(len(g['shots']) for g in gallery.values())} of "
          f"{sum(g['total'] for g in gallery.values())} screenshots; {len(stale)} stale images removed")


MIIVERSE = Path.home() / "Documents/Archive/Nintendo/miiverse_backup/assets/user"


def add_miiverse(gallery):
    """Every screenshot from the 2017 Miiverse backup: the ones attached to posts (kept with the
    post's id so the page can show them together) and the photo album. Few enough to show all."""
    def js(name):
        text = (MIIVERSE / "js" / name).read_text(encoding="utf-8")
        return json.loads(re.sub(r",\s*\]\s*;?\s*$", "]", text[text.index("=") + 1:].strip().rstrip(";")))
    titles, communities = js("title.js"), js("community.js")
    shots = defaultdict(list)
    for year in (2015, 2016, 2017):
        for p in js(f"posts/{year}.js"):
            src = MIIVERSE / "img" / "ss" / f"{p['id']}.jpg"
            if not p.get("ss") or not src.exists():
                continue
            game = titles[p["title"]]["name"] if p.get("title") in titles \
                else communities[p["community"]]["name"].replace(" Community", "")
            when = datetime.strptime(p["created_at"], "%m/%d/%Y %I:%M %p").isoformat()
            shots[game.replace("®", "")].append((when, src, p["id"]))
    for album in js("album_images.js"):
        for item in album["album"]:
            src = MIIVERSE / "img" / "ss" / f"{item['ss']}.jpg"
            if src.exists():
                when = datetime.strptime(item["created_at"].replace("Save to ", ""), "%m/%d/%Y %I:%M %p").isoformat()
                shots[album["name"].replace("®", "")].append((when, src, None))
    for game, items in shots.items():
        entries = []
        for when, src, post in sorted(items):
            name = f"mv-{src.stem}.webp"
            for kind, size in SIZES.items():
                out = OUT / kind / name
                if not out.exists():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    im = Image.open(src).convert("RGB")
                    im.thumbnail((size, size))
                    im.save(out, "WEBP", quality=72 if kind == "t" else 80)
            entries.append({"time": when, "img": name, **({"post": post} if post else {})})
        gallery[f"miiverse:{game}"] = {"game": game, "total": len(entries), "shots": entries}


PS_ARCHIVE = Path.home() / "Documents/Archive/Sony PlayStation Screenshots"
PS_CACHE = HERE / "local" / "ps_cache.json"


def stratified(items, seed):
    """Up to PER_GAME items: one at random from each of PER_GAME equal stretches by date."""
    items = sorted(items)
    if len(items) <= PER_GAME:
        return items
    rng = random.Random(seed)
    return [rng.choice(items[i * len(items) // PER_GAME:(i + 1) * len(items) // PER_GAME]) for i in range(PER_GAME)]


def save_webp(src, name):
    for kind, size in SIZES.items():
        out = OUT / kind / name
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            im = Image.open(src).convert("RGB")
            im.thumbnail((size, size))
            im.save(out, "WEBP", quality=72 if kind == "t" else 80)


def ps_when(f):
    """Capture time (console local time) from the file name, or from the photo's own metadata."""
    m = re.search(r"(\d{14})", f.name)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    exif = Image.open(f).getexif()
    stamp = exif.get(306) or exif.get_ifd(0x8769).get(36867)
    return datetime.strptime(stamp, "%Y:%m:%d %H:%M:%S") if stamp else None


def capture_layout(f):
    """The PS5 saves a picture every time a trophy pops, with the trophy drawn over it in one of
    two layouts: "banner", a curved black band across the bottom (trophy cup left, PlayStation
    logo right; PS5 games), or "flyover", a dark panel at the top left (cup, trophy name, logo
    below; PS4 games played on the PS5). None for a screenshot Ronjan took himself. Each layout
    is detected from its fixed parts, with thresholds checked by eye against the whole archive."""
    im = Image.open(f).convert("L")
    im.thumbnail((640, 360))
    w, h = im.size

    def share(box, test):
        px = im.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3]))).get_flattened_data()
        return sum(1 for p in px if test(p)) / len(px)
    dark, bright = (lambda p: p < 40), (lambda p: p > 200)
    if (share((0, 0.80, 0.03, 1), dark) > 0.8 and share((0.97, 0.80, 1, 1), dark) > 0.8
            and 0.04 < share((0.895, 0.875, 0.955, 0.96), bright) < 0.45
            and share((0.86, 0.86, 0.99, 0.99), dark) > 0.45
            and share((0.045, 0.83, 0.11, 0.97), lambda p: p > 90) > 0.08):
        return "banner"
    if (share((0.0, 0.13, 0.28, 0.24), lambda p: p < 45) > 0.55 and 0.08 < share((0.03, 0.27, 0.07, 0.32), bright) < 0.3
            and share((0.0, 0.26, 0.12, 0.33), lambda p: p < 45) > 0.85 and share((0.03, 0.15, 0.07, 0.22), lambda p: p > 90) > 0.2):
        return "flyover"
    return None


OCR_BOX = {"banner": None, "flyover": ["0.12", "0.13", "0.22", "0.12"]}


def ps_scan():
    """Every PlayStation image with its capture time, its trophy-capture layout if it is one, and
    (for those) the trophy name read off the picture. Cached by file size and mtime."""
    cache = json.loads(PS_CACHE.read_text()) if PS_CACHE.exists() else {}
    files = [f for f in sorted(PS_ARCHIVE.rglob("*")) if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
    unread = []
    for f in files:
        rel = unicodedata.normalize("NFC", str(f.relative_to(PS_ARCHIVE)))
        st = f.stat()
        c = cache.get(rel)
        if not c or c["size"] != st.st_size or c["mtime"] != st.st_mtime or "layout" not in c:
            when = (datetime.fromisoformat(c["when"]) if c and c.get("when") and c["size"] == st.st_size else ps_when(f))
            c = cache[rel] = {"size": st.st_size, "mtime": st.st_mtime, "when": when.isoformat() if when else None,
                              "layout": capture_layout(f), "text": None}
        if c["layout"] and c["text"] is None:
            unread.append((rel, f))
    for layout, box in OCR_BOX.items():  # macOS Vision: swiftc -O -o local/banner_ocr tools/banner_ocr.swift
        todo = [(rel, f) for rel, f in unread if cache[rel]["layout"] == layout]
        if not todo:
            continue
        listing = HERE / "local" / "ocr_paths.txt"
        listing.write_text("\n".join(str(f) for _, f in todo))
        read = json.loads(subprocess.run([str(HERE / "local" / "banner_ocr"), str(listing)] + (box or []),
                                         capture_output=True, text=True, check=True).stdout)
        for rel, f in todo:
            cache[rel]["text"] = read.get(str(f), "")
    PS_CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True))
    return {rel: (PS_ARCHIVE / rel, c) for rel, c in cache.items() if (PS_ARCHIVE / rel).exists()
            or (PS_ARCHIVE / unicodedata.normalize("NFD", rel)).exists()}


def add_playstation(gallery):
    """Galleries from the screenshots Ronjan took himself, and each trophy capture matched to
    the trophy it shows (by the name on its banner, then the closest time) as that trophy's
    moment. Returns the moments, keyed by unlock (entry|earned|name)."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", re.sub(r"[™®©]", "", (s or "").lower().replace("’", "'")))
    games = json.loads((HERE / "docs" / "data" / "games.json").read_text())
    unlocks = json.loads((HERE / "docs" / "data" / "unlocks.json").read_text())
    folders = json.loads((HERE / "config" / "ps_folders.json").read_text())
    by_name, by_id = {}, {r["id"]: r for r in games}
    for r in games:
        for n in [r["name"]] + r["name"].split(" + ") + [e["name"] for e in r["entries"] if e["family"] == "PlayStation"]:
            by_name.setdefault(norm(n), r)
    rows_unlocks = defaultdict(list)
    for u in unlocks:
        if u["entry"].startswith("psn:") and u["earned"]:
            rows_unlocks[u["game"]].append(u)

    def rows_for(folder):
        if folder in folders:
            target = folders[folder]
            return [by_name[norm(n)] for n in target] if target else []
        r = by_name.get(norm(folder.replace("_", ":")))
        if not r:
            raise SystemExit(f"PlayStation folder {folder!r} matches no game; add it to config/ps_folders.json")
        return [r]

    def nearest(rows, when):
        """A collection's folder: the game with trophies nearest that day"""
        days = lambda r: [abs((datetime.fromisoformat(u["earned"][:19]) - when).total_seconds()) for u in rows_unlocks[r["id"]]]
        return min(rows, key=lambda r: min(days(r), default=float("inf"))) if len(rows) > 1 else rows[0]

    files = ps_scan()
    direct, captures = defaultdict(list), []
    for rel, (path, c) in files.items():
        folder = rel.split("/")[0]
        rows = rows_for(folder)
        if not rows or not c["when"]:
            continue
        when = datetime.fromisoformat(c["when"])
        if c["layout"]:
            captures.append((rel, path, when, c["text"] or "", rows, c["layout"]))
            continue
        direct[nearest(rows, when)["id"]].append((when.isoformat(), path, rel))

    # Trophy moments: name on the picture first (it can carry game text after it, since the
    # banner is see-through), closest time to break ties; one capture per trophy. Both must be
    # within the hour: other profiles on the console earn the same trophies at other times, and
    # their captures are left out.
    ET = ZoneInfo("America/New_York")
    best, unmatched = {}, 0
    for rel, path, when, text, rows, layout in captures:
        t = when.replace(tzinfo=ET).timestamp()
        cands = [u for r in rows for u in rows_unlocks[r["id"]]]
        gap = lambda u: abs(datetime.fromisoformat(u["earned"].replace("Z", "+00:00")).timestamp() - t)
        txt = norm(text)
        named = [u for u in cands if len(norm(u["name"])) >= 2 and txt.startswith(norm(u["name"])) and gap(u) <= 3600]
        pick = min(named, key=gap) if named else None
        if not pick:
            near = [u for u in cands if gap(u) <= 120]
            pick = near[0] if len(near) == 1 else None
        if not pick:
            unmatched += 1
            continue
        k = f"{pick['entry']}|{pick['earned']}|{pick['name']}"
        if k not in best or gap(pick) < best[k][0]:
            best[k] = (gap(pick), rel, path, when)
    for gid, items in direct.items():
        row = by_id[gid]
        key = min(e["id"] for e in row["entries"] if e["id"].startswith("psn"))
        entries = []
        for when, path, rel in stratified(items, f"gameplay-tracking:ps:{row['name']}"):
            name = f"ps-{when[:19].replace('-', '').replace(':', '').replace('T', '')}-{hashlib.sha1(rel.encode()).hexdigest()[:6]}.webp"
            save_webp(path, name)
            entries.append({"time": when, "img": name})
        gallery[key] = {"game": row["name"], "total": len(items), "shots": entries}

    moments = {}
    for k, (_, rel, path, when) in best.items():
        name = f"pm-{when.strftime('%Y%m%d%H%M%S')}-{hashlib.sha1(rel.encode()).hexdigest()[:6]}.webp"
        save_webp(path, name)
        moments[k] = {"img": name, "time": when.isoformat()}
    skipped = sum(1 for rel in files if not rows_for(rel.split("/")[0]))
    layouts = Counter(c[5] for c in captures)
    print(f"playstation: {sum(len(v) for v in direct.values())} screenshots in {len(direct)} games; "
          f"{len(captures)} trophy captures ({layouts['banner']} banner, {layouts['flyover']} flyover) -> {len(moments)} moments "
          f"({unmatched} unmatched); {skipped} left out by config")
    return moments


if __name__ == "__main__":
    main()
