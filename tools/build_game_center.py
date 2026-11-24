"""Apple data export (Game Center) -> docs/data/game_center.json (one-time import, rerun after a new export).

Reads the export in local/apple_export/extracted (privacy.apple.com, arrived 2026-11-24) and
config/game_center_games.json (Ronjan's picks from the Game Center Review page). Writes, per row:
play days, unlocked achievements with dates, achievement totals, and App Store art.

Play days (Ronjan 2026-11-24): days in Game Center's launch log (10/2022 on), days an
achievement unlocked, and each game's last-played date. Download dates don't count.
The export has no achievement descriptions or icons, and no play time.

    .venv/bin/python tools/build_game_center.py
"""

import csv
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
X = HERE / "local" / "apple_export" / "extracted"
GC = X / "Game Center" / "Game Center Data.json"
STORE = X / "ams" / "Apple_Media_Services" / "Stores Activity"


def utc(s):
    """Export dates are 'MM/DD/YYYY HH:MM:SS' in UTC."""
    return datetime.strptime(s, "%m/%d/%Y %H:%M:%S").replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    cfg = json.loads((HERE / "config" / "game_center_games.json").read_text())
    export = {g["game_name"]: g for g in json.loads(GC.read_text())["game_state"]}
    launches = list(csv.DictReader(open(STORE / "Other Activity" / "GameCenter Player Activities.csv", encoding="utf-8-sig")))
    old = json.loads((HERE / "docs/data/game_center.json").read_text()) if (HERE / "docs/data/game_center.json").exists() else {"games": {}}

    unknown = sorted(set(cfg["games"]) - set(export))
    if unknown:
        raise SystemExit(f"config/game_center_games.json lists games the export doesn't have: {unknown}")
    unpicked = sorted(set(export) - set(cfg["games"]) - set(cfg.get("skip", [])))
    if unpicked:
        raise SystemExit(f"Export games with no pick in config/game_center_games.json: {unpicked}")

    rows = {}
    for gc_name, pick in cfg["games"].items():
        g = export[gc_name]
        row = rows.setdefault(pick["row"], {"export_names": [], "app_id": None, "art": None, "launch_times": [],
                                            "last_played": None, "achievements": [], "total": 0})
        row["export_names"].append(gc_name)
        row["app_id"] = row["app_id"] or pick.get("app_id")
        row["art"] = row["art"] or pick.get("art")  # App Store search hit when the id lookup comes back empty
        row["launch_times"] += sorted(r["Event Date"] for r in launches
                                      if r["App Name"] == gc_name and r["Event Type"] in ("Game init", "startgame"))
        lp = utc(g["last_played_utc"])
        row["last_played"] = max(row["last_played"] or lp, lp)
        row["total"] += len(g["achievements"])
        for a in g["achievements"]:
            if a["percentage_complete"] == 100:
                row["achievements"].append({"name": a["achievements_title"], "earned": utc(a["last_update_utc"])})

    for name, row in rows.items():
        row["achievements"].sort(key=lambda a: a["earned"])
        row["art"] = row["art"] or old["games"].get(name, {}).get("art")
        if row["app_id"] and not row["art"]:
            with urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={row['app_id']}") as r:
                res = json.load(r)["results"]
            row["art"] = res[0]["artworkUrl512"] if res else None

    out = {"games": {n: rows[n] for n in sorted(rows, key=str.lower)}}
    (HERE / "docs/data/game_center.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for n, r in out["games"].items():
        print(f"{n:38} {len(r['achievements']):3}/{r['total']:<3} achievements, {len(r['launch_times']):3} launches, art {'yes' if r['art'] else 'no'}")


if __name__ == "__main__":
    main()
