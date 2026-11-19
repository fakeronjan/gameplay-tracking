"""Store release dates per platform, to cross-check IGDB (local/igdb/store.json).

Steam (store appdetails, no key), iOS (App Store lookup), and Switch (the local eShop title
database). A store's date is that platform version's release, which for a port or remaster
is later than the original, so these confirm IGDB rather than replace it.

    .venv/bin/python tools/store_release_dates.py
"""

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "local" / "igdb" / "store.json"


def main():
    games = json.loads((HERE / "docs" / "data" / "games.json").read_text())
    ios = json.loads((HERE / "docs" / "data" / "ios.json").read_text())["games"]
    tdb = {v["id"].upper(): v for v in json.loads((HERE / "local/nintendo_lookup/titledb_US.en.json").read_text()).values() if v.get("id")}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    out = {}
    for r in games:
        dates = []
        for e in r["entries"]:
            src, _, key = e["id"].partition(":")
            if src == "steam":
                if key not in old.get("_steam", {}):
                    time.sleep(1.6)  # appdetails allows ~200 requests per 5 minutes
                    try:
                        d = json.load(urllib.request.urlopen(f"https://store.steampowered.com/api/appdetails?appids={key}&cc=us&l=en"))
                        old.setdefault("_steam", {})[key] = ((d.get(key) or {}).get("data") or {}).get("release_date", {}).get("date")
                    except Exception as ex:
                        print("steam", key, ex)
                        continue
                s = old["_steam"].get(key)
                for fmt in ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y"):
                    try:
                        dates.append({"store": "Steam", "date": datetime.strptime(s, fmt).date().isoformat()})
                        break
                    except (TypeError, ValueError):
                        pass
            elif src == "ios":
                app = ios.get(key, {}).get("app_id")
                if app:
                    if str(app) not in old.get("_ios", {}):
                        res = json.load(urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={app}"))["results"]
                        old.setdefault("_ios", {})[str(app)] = res[0].get("releaseDate") if res else None
                    s = old["_ios"].get(str(app))
                    if s:
                        dates.append({"store": "App Store", "date": s[:10]})
            elif src == "nintendo" and key.upper() in tdb and tdb[key.upper()].get("releaseDate"):
                d = str(tdb[key.upper()]["releaseDate"])
                dates.append({"store": "eShop", "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}"})
        if dates:
            out[r["id"]] = sorted({(x["store"], x["date"]) for x in dates}, key=lambda x: x[1])
    old.update({"rows": out})
    OUT.write_text(json.dumps(old, indent=1))
    print(len(out), "rows have a store date")


if __name__ == "__main__":
    main()
