"""Combine every platform into one row per game, plus one list of every unlock.

Runs after update.py (and locally after build_frozen.py). Reads docs/data/{psn,
xbox,steam,switch,miiverse}.json and config/game_merges.json; writes
docs/data/games.json and docs/data/unlocks.json.

Same game = one row. Entries join when:
  1. Sony links them (a PSN play-time record and its trophy lists), or
  2. their titles match once edition and platform labels are removed, or
  3. config/game_merges.json says so ("merge": groups of entry ids).
config/game_merges.json can also keep auto-matched entries apart ("split") and
set a row's display name ("names").
"""

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).parent
DATA = HERE / "docs" / "data"
ET = ZoneInfo("America/New_York")

# Edition and platform labels that don't make a different game. Collections
# (Legendary Edition, Trilogy, Collection, Rare Replay) are NOT here: they stay
# separate from the games they bundle.
EDITION = re.compile(
    r"\b(remastered|remaster|complete edition|definitive edition|game of the year edition|goty edition|"
    r"enhanced edition|windows edition|director'?s cut|deluxe edition|standard edition|digital edition|"
    r"for nintendo switch|nintendo switch edition|ps4 (?:&|＆|and) ps5|ps4|ps5|"
    r"playstation ?[345]|xbox one|xbox series x\|s|xbox 360 edition|pc|trophies|trophy set)\b")


def load(name):
    return json.loads((DATA / name).read_text())


def clean(name):
    """Display form: no trademark symbols, no em-dashes."""
    name = re.sub(r"[™®©]", "", name)
    return re.sub("\\s*[\u2014\u2013]\\s*", " - ", name).strip()


def key(name):
    n = clean(name).lower().replace("’", "'")
    n = re.sub(r"\([^)]*\)", " ", n)
    n = EDITION.sub(" ", n)
    n = n.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def word_key(name):
    """key() with word order ignored: "Legendary Edition: Mass Effect" = "Mass Effect Legendary Edition"."""
    return " ".join(sorted(key(name).split()))


def display_name(names):
    """Prefer the variant with the fewest all-caps words (Sony often shouts), then the shortest."""
    def shouty(n):
        return sum(1 for w in re.findall(r"[A-Za-z]{4,}", n) if w.isupper())
    return min(names, key=lambda n: (shouty(n), len(n), n))


def et_day(iso):
    if "T" not in iso:
        return iso[:10]
    if iso.endswith("Z") or "+" in iso[10:]:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    return iso[:10]  # already local time (Switch, Miiverse)


class Groups:
    """Union-find over entry ids."""

    def __init__(self):
        self.parent = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def entries_and_unlocks():
    """Every per-platform entry, keyed by a stable id, and every dated unlock."""
    entries, unlocks, links = {}, [], []

    psn = load("psn.json")
    for cid, t in psn["titles"].items():
        eid = f"psn:{cid}"
        days = []
        for tr in t["trophies"]:
            days.append(et_day(tr["earned"]))
            unlocks.append({"entry": eid, "name": tr["name"], "detail": tr["detail"], "kind": tr["type"],
                            "rarity": tr["rarity"], "earned": tr["earned"], "icon": tr.get("icon")})
        entries[eid] = {"family": "PlayStation", "platform": t["platform"].replace("PSVITA", "Vita"),
                        "name": t["name"], "days": days, "minutes": None,
                        "earned": len(t["trophies"]), "total": sum(t["defined"].values())}
    for tid, p in psn["played"].items():
        eid = f"psn-played:{tid}"
        days = [et_day(p[k]) for k in ("first_played", "last_played") if p.get(k)]
        entries[eid] = {"family": "PlayStation", "platform": "PS5" if p["category"] == "ps5_native_game" else "PS4",
                        "name": p["name"], "days": days, "minutes": p["minutes"], "earned": None, "total": None}
        lists = [f"psn:{cid}" for cid in p.get("trophy_lists", []) if f"psn:{cid}" in entries]
        # One trophy list, or several that are the same game (Mass Effect Legendary Edition's two
        # lists): join them. Several different games (a collection like Uncharted: The Nathan Drake
        # Collection): the play record stays its own row, since its hours can't be split.
        if len({word_key(entries[c]["name"]) for c in lists}) == 1:
            links += [(eid, c) for c in lists]

    for gamertag, acct in load("xbox.json")["accounts"].items():
        for tid, t in acct["titles"].items():
            eid = f"xbox:{gamertag}:{tid}"
            days = []
            for a in t["achievements"]:
                if a["earned"]:
                    days.append(et_day(a["earned"]))
                unlocks.append({"entry": eid, "name": a["name"], "detail": a["detail"], "kind": f"{a['gamerscore']}G",
                                "rarity": a["rarity"], "earned": a["earned"], "gamertag": gamertag})
            plat = "360" if "Xbox360" in t["devices"] and gamertag != "fakeronjan" else "Xbox"
            entries[eid] = {"family": "Xbox", "platform": plat, "name": t["name"], "days": days,
                            "minutes": t.get("minutes"), "earned": len(t["achievements"]),
                            "total": t["achievements_total"], "gamertag": gamertag}

    for appid, g in load("steam.json")["games"].items():
        eid = f"steam:{appid}"
        ach = g["achievements"] or {}
        days = [et_day(a["earned"]) for a in ach.get("earned", [])]
        if g["last_played"] and g["minutes"]:
            days.append(et_day(g["last_played"]))
        for a in ach.get("earned", []):
            unlocks.append({"entry": eid, "name": a["name"], "detail": a["detail"], "kind": "achievement",
                            "rarity": a["rarity"], "earned": a["earned"]})
        entries[eid] = {"family": "Steam", "platform": "PC", "name": g["name"], "days": days,
                        "minutes": g["minutes"] or None, "earned": len(ach.get("earned", [])) if ach else None,
                        "total": ach.get("total")}

    for name, g in load("switch.json")["games"].items():
        entries[f"switch:{name}"] = {"family": "Nintendo", "platform": "Switch", "name": name,
                                     "days": [c["time"][:10] for c in g["captures"]], "minutes": None,
                                     "earned": None, "total": None, "captures": len(g["captures"])}

    posts = defaultdict(list)
    for p in load("miiverse.json")["posts"]:
        posts[p["game"]].append(p["date"][:10])
    for name, days in posts.items():
        entries[f"miiverse:{name}"] = {"family": "Nintendo", "platform": "Wii U/3DS", "name": name,
                                       "days": days, "minutes": None, "earned": None, "total": None}

    # A PSN play record with no activity dates and no trophies adds nothing
    return entries, unlocks, links


def build():
    cfg = json.loads((HERE / "config" / "game_merges.json").read_text())
    entries, unlocks, links = entries_and_unlocks()
    split = {e for group in cfg.get("split", []) for e in group}

    g = Groups()
    for e in entries:
        g.find(e)
    for a, b in links:
        if a in entries and b in entries:
            g.union(a, b)
    by_key = defaultdict(list)
    for eid, e in entries.items():
        if eid not in split:
            by_key[key(e["name"])].append(eid)
    for ids in by_key.values():
        for other in ids[1:]:
            g.union(ids[0], other)
    for group in cfg.get("merge", []):
        for other in group[1:]:
            g.union(group[0], other)

    rows = defaultdict(list)
    for eid in entries:
        rows[g.find(eid)].append(eid)

    games = []
    for ids in rows.values():
        es = [entries[i] for i in ids]
        days = sorted({d for e in es for d in e["days"]})
        if not days:
            continue  # owned or launched, but never any dated activity
        name = next((cfg["names"][i] for i in ids if i in cfg.get("names", {})), None) \
            or display_name({clean(e["name"]) for e in es})
        game_id = re.sub(r"[^a-z0-9]+", "-", key(name)).strip("-") or min(ids)
        mins = [e["minutes"] for e in es if e["minutes"]]
        games.append({
            "id": game_id, "name": name, "first": days[0], "last": days[-1], "days": days,
            "families": sorted({e["family"] for e in es}),
            "hours": round(sum(mins) / 60, 1) if mins else None,
            "entries": sorted(({"id": i, **{k: v for k, v in entries[i].items() if k != "days"},
                                "name": clean(entries[i]["name"]),
                                "first": min(entries[i]["days"], default=None),
                                "last": max(entries[i]["days"], default=None)} for i in ids),
                              key=lambda x: (x["first"] or "9", x["id"])),
        })
    # Unique ids (two different games can share a key-derived slug only through a split)
    seen = defaultdict(int)
    for row in sorted(games, key=lambda r: r["first"]):
        seen[row["id"]] += 1
        if seen[row["id"]] > 1:
            row["id"] += f"-{seen[row['id']]}"
    games.sort(key=lambda r: (r["last"], r["name"]), reverse=True)

    entry_game = {e["id"]: row["id"] for row in games for e in row["entries"]}
    for u in unlocks:
        u["game"] = entry_game.get(u["entry"])
        u["name"] = clean(u["name"] or "")
    unlocks = [u for u in unlocks if u["game"]]
    unlocks.sort(key=lambda u: (u["earned"] or "", u["game"], u["name"]), reverse=True)

    (DATA / "games.json").write_text(json.dumps(games, indent=1, ensure_ascii=False) + "\n")
    (DATA / "unlocks.json").write_text(json.dumps(unlocks, indent=1, ensure_ascii=False) + "\n")
    multi = sum(1 for r in games if len(r["families"]) > 1)
    print(f"games: {len(games)} rows from {len(entries)} entries ({multi} on more than one platform family); "
          f"{len(unlocks)} unlocks")


if __name__ == "__main__":
    build()
