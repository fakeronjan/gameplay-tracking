"""Match every game row to IGDB and pull its original North American release date.

One-time import (Ronjan 2026-11-18): writes local/igdb/matches.json with every candidate and a
confidence, for review; the reviewed result goes to config/release_dates.json. Credentials come
from Keychain (igdb-client-id, igdb-client-secret), never from files.

    .venv/bin/python tools/igdb_release_dates.py
"""

import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "local" / "igdb"
NA, WORLD = 2, 8  # IGDB release_region ids
# IGDB platform ids for the consoles the site names
PLAT = {"Switch": 130, "Switch 2": 508, "PS5": 167, "PS4": 48, "PS3": 9, "Vita": 46, "360": 12, "Xbox": 49,
        "PC": 6, "3DS": 37, "Wii U": 41, "iOS": 39, "Wii U/3DS": 41}
MAIN_TYPES = {0, 8, 9, 10, 11}  # main game, remake, remaster, expanded game, port


def keychain(s):
    return subprocess.run(["security", "find-generic-password", "-s", s, "-w"], capture_output=True, text=True, check=True).stdout.strip()


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[™®©]", "", s).replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", s)


def main():
    cid, secret = keychain("igdb-client-id"), keychain("igdb-client-secret")
    tok = json.load(urllib.request.urlopen(urllib.request.Request("https://id.twitch.tv/oauth2/token", method="POST",
        data=urllib.parse.urlencode({"client_id": cid, "client_secret": secret, "grant_type": "client_credentials"}).encode())))["access_token"]

    def igdb(q):
        for attempt in range(4):
            try:
                time.sleep(0.27)  # 4 requests a second
                return json.load(urllib.request.urlopen(urllib.request.Request("https://api.igdb.com/v4/games", data=q.encode(),
                    headers={"Client-ID": cid, "Authorization": "Bearer " + tok})))
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                time.sleep(1 + attempt)
        raise SystemExit("IGDB kept rate-limiting")

    games = json.loads((HERE / "docs" / "data" / "games.json").read_text())
    cache = json.loads((OUT / "raw.json").read_text()) if (OUT / "raw.json").exists() else {}
    fields = "fields name,game_type,first_release_date,release_dates.date,release_dates.release_region,release_dates.platform,platforms,version_parent;"
    results = {}
    for r in games:
        name = r["name"]
        base = name.split(" + ")[0]
        m = re.search(r"\s\(([^)]+)\)$", base)
        suffix = m.group(1) if m else None
        base = re.sub(r"\s\([^)]+\)$", "", base)
        if base not in cache:
            q = base.replace('"', "")
            cache[base] = igdb(f'search "{q}"; {fields} limit 15;')
        plats = {PLAT.get(p.strip()) for e in r["entries"] for p in e.get("platform", "").replace("/", ",").split(",")} - {None}
        cands = []
        for g in cache[base]:
            if g.get("version_parent"):
                continue
            exact = norm(g["name"]) == norm(base)
            rds = g.get("release_dates") or []
            # Original NA release: the earliest North American (or worldwide) date on any platform
            na = sorted(d["date"] for d in rds if d.get("date") and d.get("release_region") in (NA, WORLD))
            when = na[0] if na else g.get("first_release_date")
            if not when:
                continue
            day = datetime.fromtimestamp(when, timezone.utc).date().isoformat()
            score = (3 if exact else 0) + (1 if g.get("game_type") in MAIN_TYPES else -2) + (1 if plats & set(g.get("platforms") or []) else 0)
            if suffix and re.fullmatch(r"\d{4}", suffix):
                score += 2 if day[:4] == suffix else -2
            cands.append({"igdb": g["id"], "name": g["name"], "date": day, "score": score, "exact": exact,
                          "type": g.get("game_type"), "region": "NA" if na else "first release"})
        cands.sort(key=lambda c: (-c["score"], c["date"]))
        top = cands[0] if cands else None
        if not top:
            conf = "none"
        elif top["exact"] and (len(cands) == 1 or cands[1]["score"] < top["score"]):
            conf = "high"
        elif top["exact"]:
            conf = "medium"
        else:
            conf = "low"
        results[r["id"]] = {"name": name, "first_played": r["first"], "confidence": conf, "pick": top, "candidates": cands[:6]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "raw.json").write_text(json.dumps(cache))
    (OUT / "matches.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    from collections import Counter
    print(Counter(v["confidence"] for v in results.values()))


if __name__ == "__main__":
    main()
