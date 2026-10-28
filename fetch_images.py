"""Keep local copies of every unlock icon and game's art, so the page never depends on
platform image servers (Xbox 360's is a 2010 leftover; Sony's URLs have changed before).

Reads docs/data/games.json and unlocks.json, downloads any image not stored yet,
shrinks it to webp (64 px icons, 256 px art) under docs/img/, and writes the local
path back into each record as "img". Runs after build_games.py.
"""

import hashlib
import io
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
DATA = HERE / "docs" / "data"
IMG = HERE / "docs" / "img"
SIZES = {"u": 64, "g": 256}  # unlock icons, game art


def local_path(kind, url):
    if not url.startswith("http"):
        return url  # already a local file (Miiverse icons)
    return f"img/{kind}/{hashlib.sha1(url.encode()).hexdigest()[:16]}.webp"


def fetch(kind, url):
    """Download and shrink one image; True when the file exists afterwards."""
    out = HERE / "docs" / local_path(kind, url)
    if out.exists():
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fakeronjan-gameplay-tracking"})
        data = urllib.request.urlopen(req, timeout=30).read()
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        im.thumbnail((SIZES[kind], SIZES[kind]))
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, "WEBP", quality=82)
        return True
    except Exception as e:
        print(f"  {kind} {url[:90]}: {e}")
        return False


def main():
    games = json.loads((DATA / "games.json").read_text())
    unlocks = json.loads((DATA / "unlocks.json").read_text())
    jobs = {("g", g["art"]) for g in games if g.get("art")} | {("u", u["icon"]) for u in unlocks if u.get("icon")}
    jobs = {(k, url) for k, url in jobs if url.startswith("http")}
    with ThreadPoolExecutor(8) as pool:
        ok = dict(zip(jobs, pool.map(lambda j: fetch(*j), jobs)))
    for g in games:
        g["img"] = local_path("g", g["art"]) if g.get("art") and ok.get(("g", g["art"]), True) else None
    for u in unlocks:
        u["img"] = local_path("u", u["icon"]) if u.get("icon") and ok.get(("u", u["icon"]), True) else None
    (DATA / "games.json").write_text(json.dumps(games, indent=1, ensure_ascii=False) + "\n")
    (DATA / "unlocks.json").write_text(json.dumps(unlocks, indent=1, ensure_ascii=False) + "\n")
    print(f"images: {sum(ok.values())} of {len(ok)} stored; "
          f"{sum(1 for g in games if g['img'])} of {len(games)} games and "
          f"{sum(1 for u in unlocks if u['img'])} of {len(unlocks)} unlocks have one")


if __name__ == "__main__":
    main()
