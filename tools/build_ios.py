"""iOS screenshots -> docs/data/ios.json (one-time import, rerun after a re-sort).

Reads Ronjan's labels (local/ios_screens/labels_v2.json, from the 2026-11-18 review) and
config/ios_games.json. Writes each game's screenshot times and device (no images: galleries
are built separately after a hand check), plus App Store art.

    .venv/bin/python tools/build_ios.py
"""

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LOCAL = HERE / "local" / "ios_screens"


def device(w, h):
    r = max(w, h) / min(w, h)
    return "iPad" if r < 1.6 else "iPhone"  # iPads are 4:3 to 1.44:1; iPhones 16:9 and taller


def main():
    cfg = json.loads((HERE / "config" / "ios_games.json").read_text())
    labels = json.loads((LOCAL / "labels_v2.json").read_text())
    man = {v["file"]: v for v in json.loads((LOCAL / "manifest.json").read_text()).values()}
    old = json.loads((HERE / "docs/data/ios.json").read_text()) if (HERE / "docs/data/ios.json").exists() else {"games": {}}
    games = {}
    for label, g in cfg["games"].items():
        files = sorted(f for f, l in labels["label"].items() if l == label)
        if not files:
            raise SystemExit(f"config/ios_games.json lists {label!r}, which no screenshot has")
        caps = []
        for f in files:
            m = man[f]
            caps.append({"time": m["time"], "device": device(m["w"], m["h"]), "file": f,
                         **({"dup_of": labels["dup_of"][f]} if f in labels["dup_of"] else {})})
        art = g.get("art") or old["games"].get(g["name"], {}).get("art")
        if g["app_id"] and not art:
            with urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={g['app_id']}") as r:
                res = json.load(r)["results"]
            art = res[0]["artworkUrl512"] if res else None
        games[g["name"]] = {"app_id": g["app_id"], "art": art, "captures": caps,
                            **{k: g[k] for k in ("estimated_minutes", "gallery") if k in g}}
    (HERE / "docs/data/ios.json").write_text(json.dumps({"games": games}, indent=1, ensure_ascii=False) + "\n")
    for n, g in games.items():
        days = {c["time"][:10] for c in g["captures"]}
        print(f"{n:20} {sum(1 for c in g['captures'] if 'dup_of' not in c):4} screenshots, {len(days):3} days, art {'yes' if g['art'] else 'no'}")


if __name__ == "__main__":
    main()
