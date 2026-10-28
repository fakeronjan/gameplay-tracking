"""One-time import of sources that no longer change: Xbox, Switch screenshots, Miiverse.

Runs locally only. Inputs are raw dumps and archives on this Mac (local/ and
~/Documents/Archive/Nintendo), never committed; outputs go to docs/data/.

    python build_frozen.py
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
LOCAL = HERE / "local"
CONFIG = HERE / "config"
DATA = HERE / "docs" / "data"
SWITCH_DIR = Path.home() / "Documents/Archive/Nintendo/Nintendo Switch Screenshots"

# Microsoft's placeholder when an Xbox 360 unlock time wasn't recorded
NO_DATE = "1753-01-01"
XBOX_ACCOUNTS = [  # (gamertag, local dump folder)
    ("thesurfshop19", "xbox_thesurfshop19"),
    ("rogerage", "xbox_rogerage"),
    ("fakeronjan", "xbox_fakeronjan"),
]


def save(name, data):
    (DATA / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def xbox_achievement(a):
    if "progressState" in a:  # Xbox One and later
        gs = next((int(r["value"]) for r in a.get("rewards", []) if r["type"] == "Gamerscore"), 0)
        when = a["progression"]["timeUnlocked"]
    else:  # Xbox 360
        gs, when = a["gamerscore"], a["timeUnlocked"]
    return {"name": a["name"], "detail": a.get("description"), "gamerscore": gs,
            "earned": None if when.startswith(NO_DATE) else when,
            "rarity": (a.get("rarity") or {}).get("currentPercentage")}


def build_xbox():
    excluded = json.loads((CONFIG / "xbox_overrides.json").read_text())["exclude_title_ids"]
    accounts = {}
    for gamertag, folder in XBOX_ACCOUNTS:
        src = LOCAL / folder
        minutes = {}
        for f in (src / "stats").glob("*.json") if (src / "stats").exists() else []:
            for coll in json.loads(f.read_text())["content"].get("statlistscollection", []):
                for st in coll["stats"]:
                    if st["name"] == "MinutesPlayed" and "value" in st:
                        minutes[f.stem] = int(st["value"])
        titles = {}
        for t in json.loads((src / "title_list.json").read_text())["content"]["titles"]:
            if t["titleId"] in excluded:
                continue
            ach = []
            dump = src / "titles" / f"{t['titleId']}.json"
            if dump.exists():
                d = json.loads(dump.read_text())["data"]
                ach = [xbox_achievement(a) for a in d.get("content", d)["achievements"]
                       if a.get("unlocked") or a.get("progressState") == "Achieved"]
                ach.sort(key=lambda a: (a["earned"] or "", a["name"]))
            titles[t["titleId"]] = {
                "name": t["name"], "devices": t["devices"], "image": t.get("displayImage"),
                "gamerscore": t["achievement"]["currentGamerscore"],
                "gamerscore_total": t["achievement"]["totalGamerscore"],
                "achievements_total": t["achievement"]["totalAchievements"],
                "minutes": minutes.get(t["titleId"]), "achievements": ach,
            }
        accounts[gamertag] = {"gamerscore": sum(t["gamerscore"] for t in titles.values()), "titles": titles}
        print(f"xbox {gamertag}: {len(titles)} titles, {accounts[gamertag]['gamerscore']} gamerscore")
    save("xbox.json", {"accounts": accounts})


def build_switch():
    names = json.loads((CONFIG / "switch_game_names.json").read_text())
    file_overrides = json.loads((CONFIG / "switch_overrides.json").read_text())["file_overrides"]
    games = defaultdict(lambda: {"captures": [], "ids": set()})
    dropped = 0
    for f in sorted(SWITCH_DIR.rglob("*")):
        m = re.fullmatch(r"(\d{14})\d\d-([0-9A-F]{32})\.(jpg|mp4)", f.name)
        if not m:
            continue
        stamp, game_id, ext = m.groups()
        game_id = file_overrides.get(f.name, {}).get("game_id", game_id)
        info = names[game_id]
        if info.get("exclude"):
            dropped += 1
            continue
        name = info.get("display") or info["name"]
        when = datetime.strptime(stamp, "%Y%m%d%H%M%S").isoformat()  # console local time
        games[name]["captures"].append({"time": when, "video": ext == "mp4"})
        games[name]["ids"].add(game_id)
    for g in games.values():
        g["captures"].sort(key=lambda c: c["time"])
        g["ids"] = sorted(g["ids"])  # screenshot game IDs: stable even when a name is corrected
    print(f"switch: {len(games)} games, {sum(len(g['captures']) for g in games.values())} captures, {dropped} dropped")
    save("switch.json", {"note": "Capture times are the console's local time", "games": dict(games)})


def build_miiverse():
    posts = json.loads((LOCAL / "miiverse_posts.json").read_text())
    for p in posts:
        p["game"] = p["game"].replace("®", "")
    print(f"miiverse: {len(posts)} posts")
    save("miiverse.json", {"note": "Post times are local time as shown by Miiverse", "posts": posts})


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    build_xbox()
    build_switch()
    build_miiverse()
