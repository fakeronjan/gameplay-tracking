"""One-time import of sources that no longer change: Xbox, Switch screenshots, Miiverse.

Runs locally only. Inputs are raw dumps and archives on this Mac (local/ and
~/Documents/Archive/Nintendo), never committed; outputs go to docs/data/.

    python build_frozen.py
"""

import json
import re
import shutil
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
# thesurfshop19's lastTimePlayed is 9/4/2010 for all 105 titles (a migration date, not play)
XBOX_BOGUS_LAST_PLAYED = {"thesurfshop19"}
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
        icon = next((m["url"] for m in a.get("mediaAssets", []) if m.get("type") == "Icon"), None)
    else:  # Xbox 360: Microsoft's legacy image server, addressed by title and image id
        gs, when = a["gamerscore"], a["timeUnlocked"]
        icon = f"https://image-ssl.xboxlive.com/global/t.{a['titleId']:x}/ach/0/{a['imageId']:x}"
    return {"name": a["name"], "detail": a.get("description"), "gamerscore": gs,
            "earned": None if when.startswith(NO_DATE) else when,
            "rarity": (a.get("rarity") or {}).get("currentPercentage"), "icon": icon}


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
                "last_played": None if gamertag in XBOX_BOGUS_LAST_PLAYED else (t.get("titleHistory") or {}).get("lastTimePlayed"),
            }
        accounts[gamertag] = {"gamerscore": sum(t["gamerscore"] for t in titles.values()), "titles": titles}
        print(f"xbox {gamertag}: {len(titles)} titles, {accounts[gamertag]['gamerscore']} gamerscore")
    save("xbox.json", {"accounts": accounts})


# Original Switch: <date+time><2-digit seq>-<32 hex game id>; Switch 2 appends "L" to the id
SWITCH_FILE = re.compile(r"(\d{14})\d\d-([0-9A-F]{32})(L?)\.(jpg|mp4)")


def build_switch():
    names = json.loads((CONFIG / "switch_game_names.json").read_text())
    file_overrides = json.loads((CONFIG / "switch_overrides.json").read_text())["file_overrides"]
    games = defaultdict(lambda: {"captures": [], "ids": set(), "consoles": set()})
    dropped, unrecognized, unnamed = 0, [], defaultdict(int)
    for f in sorted(SWITCH_DIR.rglob("*")):
        if not f.is_file() or f.name == ".DS_Store":
            continue
        m = SWITCH_FILE.fullmatch(f.name)
        if not m:
            unrecognized.append(str(f.relative_to(SWITCH_DIR)))
            continue
        stamp, game_id, switch2, ext = m.groups()
        game_id = file_overrides.get(f.name, {}).get("game_id", game_id)
        if game_id not in names:
            unnamed[game_id] += 1
            continue
        info = names[game_id]
        if info.get("exclude"):
            dropped += 1
            continue
        name = info.get("display") or info["name"]
        when = datetime.strptime(stamp, "%Y%m%d%H%M%S").isoformat()  # console local time
        games[name]["captures"].append({"time": when, "video": ext == "mp4"})
        games[name]["ids"].add(game_id)
        games[name]["consoles"].add("Switch 2" if switch2 else "Switch")
    # Never skip silently: a new filename format or an unnamed game stops the build
    if unrecognized or unnamed:
        raise SystemExit("Switch screenshots need attention:\n"
                         + "".join(f"  unrecognized file: {u}\n" for u in unrecognized)
                         + "".join(f"  no name for game id {g} ({n} files); add it to config/switch_game_names.json\n"
                                   for g, n in unnamed.items()))
    for g in games.values():
        g["captures"].sort(key=lambda c: c["time"])
        g["ids"] = sorted(g["ids"])  # screenshot game IDs: stable even when a name is corrected
        g["consoles"] = sorted(g["consoles"])
        g["art"] = next((names[i]["art"] for i in g["ids"] if names[i].get("art")), None)
    print(f"switch: {len(games)} games, {sum(len(g['captures']) for g in games.values())} captures, {dropped} dropped")
    save("switch.json", {"note": "Capture times are the console's local time", "games": dict(games)})


MIIVERSE = Path.home() / "Documents/Archive/Nintendo/miiverse_backup/assets/user"


def miiverse_js(name):
    text = (MIIVERSE / "js" / name).read_text(encoding="utf-8")
    return json.loads(re.sub(r",\s*\]\s*;?\s*$", "]", text[text.index("=") + 1:].strip().rstrip(";")))


def build_miiverse():
    """Posts from the 2017 Miiverse backup, with each game's icon copied into docs/img/miiverse/."""
    titles, communities = miiverse_js("title.js"), miiverse_js("community.js")
    out_dir = HERE / "docs" / "img" / "miiverse"
    out_dir.mkdir(parents=True, exist_ok=True)
    posts = []
    for year in (2015, 2016, 2017):
        for p in miiverse_js(f"posts/{year}.js"):
            if p.get("title") in titles:
                game, icon = titles[p["title"]]["name"], p["title"]
            else:
                c = communities[p["community"]]
                game, icon = c["name"].replace(" Community", ""), c["icon"]
            src = MIIVERSE / "img" / "icon" / f"{icon}.png"
            if src.exists() and not (out_dir / src.name).exists():
                shutil.copy(src, out_dir / src.name)
            posts.append({"date": datetime.strptime(p["created_at"], "%m/%d/%Y %I:%M %p").isoformat(),
                          "game": game.replace("®", ""), "kind": p.get("subtype", "Post"), "body": p.get("body"),
                          "id": p["id"], "art": f"img/miiverse/{icon}.png" if src.exists() else None})
    posts.sort(key=lambda p: p["date"])
    print(f"miiverse: {len(posts)} posts")
    save("miiverse.json", {"note": "Post times are local time as shown by Miiverse", "posts": posts})


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    build_xbox()
    build_switch()
    build_miiverse()
