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
    r"\b(remastered|remaster|complete edition|(?:the )?definitive edition|game of the year edition|goty edition|"
    r"enhanced edition|windows edition|special edition|for windows|for ios|director'?s cut|deluxe edition|standard edition|digital edition|"
    r"for nintendo switch|nintendo switch edition|ps4 (?:&|＆|and) ps5|ps4|ps5|"
    r"playstation ?[345]|xbox one|xbox series x ?\| ?s|xbox 360 edition|pc|trophies|trophy set)\b")


def load(name):
    return json.loads((DATA / name).read_text())


def clean(name):
    """Display form: no trademark symbols, no em-dashes, straight apostrophes."""
    name = re.sub(r"[™®©]", "", name).replace("’", "'")
    name = "".join(ROMAN.get(c, c) for c in name)
    return re.sub("\\s*[\u2014\u2013]\\s*", " - ", name).strip()


# Platform and trophy-system labels that platforms bolt onto a game's name
LABELS = re.compile(
    r"\s*(\((?:PlayStation\s*\d|PS\s*\d|PS Vita|Vita|Xbox One|Xbox Series X\|S|GER|EU|EUR|US|UK|JP)\)|"
    r"PS4\s*[&＆]\s*PS5|PS[345]|(?:for )?Xbox Series X ?\| ?S|Next Generation|\d+(?:st|nd|rd|th) Anniversary|Trophies|Trophy Set|Trophy pack\.?|Trophy)\s*$",
    re.I)
# All-caps words that are real acronyms or official all-caps names, kept as is
ACRONYMS = {"LEGO", "NCAA", "WWE", "MLB", "NBA", "NFL", "NHL", "UFC", "FIFA", "DOOM", "BIGS", "FPS", "HD", "DX", "UNO",
            "SNES", "KOTOR", "SOTN", "TMNT", "XCOM", "DCUO", "EA", "FC", "CE", "RPG", "NES", "UFO", "DLC", "PGA"}
ROMAN = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI", "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X"}


SMALL = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "vs."}


def display(name):
    """A game's name as the page shows it: clean, labels removed, shouting toned down."""
    name = clean(name)
    while LABELS.search(name):
        name = LABELS.sub("", name).strip()
    name = re.sub(r"^EA SPORTS (?!FC\b|College Football\b)", "", name, flags=re.I)  # "EA SPORTS Madden NFL 27" = Madden NFL 27; FC and College Football keep it, it is their name
    words = re.findall(r"[A-Za-z][A-Za-z']*", name)
    shouting = sum(w.isupper() and len(w) > 1 for w in words) > len(words) / 2

    def calm(m):
        w = m.group(0)
        if w in ACRONYMS or re.fullmatch(r"[IVXLCDM]+", w) or (len(w) < 4 and not shouting):
            return w
        if shouting and w.lower() in SMALL and m.start() > 0:
            return w.lower()
        return w.capitalize()
    # An all-caps title gets every word calmed; a mixed title only its long all-caps words
    name = re.sub(r"(?<!-)\b[A-Z][A-Z']+\b(?!-)", calm, name)
    return re.sub(r"\bvs\.", "vs.", name, flags=re.I)


def key(name):
    """Matching form: lowercase, no punctuation, no edition or platform labels."""
    n = clean(name).lower()
    n = re.sub(r"\([^)]*\)", " ", n)
    n = EDITION.sub(" ", n)
    n = n.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def word_key(name):
    """key() with word order ignored: "Legendary Edition: Mass Effect" = "Mass Effect Legendary Edition"."""
    return " ".join(sorted(key(name).split()))


def display_name(entries):
    """Pick the row's name from its entries' names. Never drop a standalone number another
    variant has (College Football 25), prefer the base name over an edition label (The Witcher 3,
    not its Remastered store listing), then store names over trophy-list names, then the shortest."""
    def numbers(n):
        return set(re.findall(r"\b\d+\b", key(n)))
    nums = set().union(*(numbers(display(e["name"])) for e in entries))

    def score(e):
        n = display(e["name"])
        return (len(nums - numbers(n)), bool(EDITION.search(n.lower())), e["id"].startswith("psn:"), len(n), n)
    return display(min(entries, key=score)["name"])


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


def entries_and_unlocks(cfg=None):
    """Every per-platform entry, keyed by a stable id, and every dated unlock."""
    cfg = cfg if cfg is not None else json.loads((HERE / "config" / "game_merges.json").read_text())
    entries, unlocks, links = {}, [], []

    psn = load("psn.json")
    for cid, t in psn["titles"].items():
        eid = f"psn:{cid}"
        days = []
        for tr in t["trophies"]:
            days.append(et_day(tr["earned"]))
            unlocks.append({"entry": eid, "name": tr["name"], "detail": tr["detail"], "kind": tr["type"],
                            "rarity": tr["rarity"], "earned": tr["earned"], "icon": tr.get("icon"), "group": tr.get("group")})
        entries[eid] = {"family": "PlayStation", "platform": t["platform"].replace("PSVITA", "Vita"),
                        "name": t["name"], "days": days, "minutes": None, "art": t.get("icon"),
                        "earned": len(t["trophies"]), "total": sum(t["defined"].values())}
    for gamertag, acct in load("xbox.json")["accounts"].items():
        for tid, t in acct["titles"].items():
            eid = f"xbox:{gamertag}:{tid}"
            days = []
            for a in t["achievements"]:
                if a["earned"]:
                    days.append(et_day(a["earned"]))
                unlocks.append({"entry": eid, "name": a["name"], "detail": a["detail"], "kind": f"{a['gamerscore']}G",
                                "rarity": a["rarity"], "earned": a["earned"], "gamertag": gamertag, "icon": a.get("icon")})
            if t.get("last_played"):
                days.append(et_day(t["last_played"]))
            plat = "360" if "Xbox360" in t["devices"] and gamertag != "fakeronjan" else "Xbox"
            entries[eid] = {"family": "Xbox", "platform": plat, "name": t["name"], "days": days,
                            "minutes": t.get("minutes"), "earned": len(t["achievements"]),
                            "total": t["achievements_total"], "gamertag": gamertag, "art": t.get("image")}

    for appid, g in load("steam.json")["games"].items():
        eid = f"steam:{appid}"
        ach = g["achievements"] or {}
        days = [et_day(a["earned"]) for a in ach.get("earned", [])]
        if g["last_played"] and g["minutes"]:
            days.append(et_day(g["last_played"]))
        for a in ach.get("earned", []):
            unlocks.append({"entry": eid, "name": a["name"], "detail": a["detail"], "kind": "achievement",
                            "rarity": a["rarity"], "earned": a["earned"], "icon": a.get("icon")})
        entries[eid] = {"family": "Steam", "platform": "PC", "name": g["name"], "days": days,
                        "minutes": g["minutes"] or None, "earned": len(ach.get("earned", [])) if ach else None,
                        "total": ach.get("total"),
                        "art": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"}

    for name, g in load("switch.json")["games"].items():
        entries[f"switch:{g['ids'][0]}"] = {"family": "Nintendo", "platform": ", ".join(g.get("consoles", ["Switch"])), "name": name,
                                     "days": [c["time"][:10] for c in g["captures"]], "minutes": None,
                                     "earned": None, "total": None, "art": g.get("art"),
                                     # Videos count as days played, never in the screenshot count
                                     "captures": sum(1 for c in g["captures"] if not c.get("video"))}

    posts, art = defaultdict(list), {}
    for p in load("miiverse.json")["posts"]:
        posts[p["game"]].append(p["date"][:10])
        art[p["game"]] = art.get(p["game"]) or p.get("art")
    for name, days in posts.items():
        entries[f"miiverse:{name}"] = {"family": "Nintendo", "platform": "Wii U/3DS", "name": name,
                                       "days": days, "minutes": None, "earned": None, "total": None, "art": art[name]}

    split_collections(entries, unlocks, cfg.get("collections", {}))
    for tid, p in psn["played"].items():
        add_play_record(entries, links, f"psn-played:{tid}", p)
    for u in unlocks:
        u.pop("group", None)
    return entries, unlocks, links


def split_collections(entries, unlocks, rules):
    """Split a collection's single trophy or achievement list into one entry per game it holds,
    so each game's unlocks join that game's row. Rules, in config/game_merges.json "collections":
      {"by": "prefix", "parts": {"ME1": "Mass Effect", ...}}  description starts "ME1: ..."
      {"by": "group",  "parts": {"default": "Uncharted 4: ...", "001": "..."}}  PSN trophy group
      {"by": "all",    "parts": {"*": "Mass Effect"}}  the whole list is one game
    The list's own hours (Xbox) are split by days with unlocks in each part, as an estimate."""
    missing = sorted(set(rules) - set(entries))
    if missing:
        raise SystemExit(f"config/game_merges.json collections name entries that don't exist: {missing}")
    for eid, rule in rules.items():
        parent = entries.pop(eid)
        parts = {}
        for u in unlocks:
            if u["entry"] != eid:
                continue
            if rule["by"] == "prefix":
                m = re.match(r"\s*([A-Za-z]+\d+)\b", u["detail"] or "")
                key_ = m.group(1) if m else None
            elif rule["by"] == "group":
                key_ = u.get("group") or "default"
            else:
                key_ = "*"
            if key_ not in rule["parts"]:
                raise SystemExit(f"{eid}: unlock {u['name']!r} matches no part of its collection rule")
            sub = f"{eid}#{key_}"
            part = parts.setdefault(sub, {**parent, "name": rule["parts"][key_], "days": [], "earned": 0,
                                          "total": None, "minutes": None})
            part["earned"] += 1
            if u["earned"]:
                part["days"].append(et_day(u["earned"]))
            u["entry"] = sub
        if rule["by"] == "all":  # the whole list is one game, so its trophy total is that game's
            for part in parts.values():
                part["total"] = parent.get("total")
        allocate(parent.get("minutes"), parent.get("sessions"), list(parts.values()), lambda e: len(set(e["days"])),
                 parent["name"])
        entries.update(parts)
        entries[eid] = {"split_into": sorted(parts)}  # placeholder so play records can find the parts


def allocate(minutes, sessions, parts, weight, source):
    """Share a collection's hours and sessions across its games by weight (days played).
    One game with any weight gets everything, and that's exact; several get an estimate."""
    weights = [weight(e) for e in parts]
    total = sum(weights)
    if not total:
        return False
    estimated = sum(1 for w in weights if w) > 1
    for e, w in zip(parts, weights):
        if not w:
            continue
        if minutes:
            e["minutes"] = (e.get("minutes") or 0) + round(minutes * w / total)
        if sessions:
            e["sessions"] = (e.get("sessions") or 0) + round(sessions * w / total)
        if estimated:
            e["estimated"] = True
            e.setdefault("estimated_from", []).append(display(source))
    return True


def add_play_record(entries, links, eid, p):
    """A PS4/PS5 play record (hours, sessions, first and last played) and Sony's link to its
    trophy lists. One game behind it: link it to that game. A collection of several games
    (Uncharted: The Nathan Drake Collection): share its hours across them by the days with
    trophies in each, counting only days inside the record's own first-to-last window, so a
    collection that Sony renamed an older purchase to doesn't pull in other games' years."""
    record = {"family": "PlayStation", "platform": "PS5" if p["category"] == "ps5_native_game" else "PS4",
              "name": p["name"], "days": [et_day(p[k]) for k in ("first_played", "last_played") if p.get(k)],
              "minutes": p["minutes"], "sessions": p.get("play_count"), "earned": None, "total": None,
              "art": p.get("image")}
    parts = []
    for cid in p.get("trophy_lists", []):
        e = entries.get(f"psn:{cid}")
        if e is None:
            continue
        parts += [s for s in e["split_into"]] if "split_into" in e else [f"psn:{cid}"]
    games = {word_key(entries[c]["name"]) for c in parts}
    if len(games) <= 1:
        entries[eid] = record
        links += [(eid, c) for c in parts]
        return
    first, last = (min(record["days"]), max(record["days"])) if record["days"] else (None, None)
    in_window = lambda e: len({d for d in e["days"] if first and first <= d <= last})
    comps = [entries[c] for c in parts]
    for weight in (in_window, lambda e: len(set(e["days"]))):
        if allocate(record["minutes"], record["sessions"], comps, weight, record["name"]):
            sole = [e for e in comps if weight(e)]
            if len(sole) == 1:  # all of it is one game's, so its first and last played dates are too
                sole[0]["days"] = sole[0]["days"] + record["days"]
            return
    entries[eid] = record  # no trophies anywhere to go by: keep the record as its own row


def build():
    cfg = json.loads((HERE / "config" / "game_merges.json").read_text())
    entries, unlocks, links = entries_and_unlocks(cfg)
    entries = {k: v for k, v in entries.items() if "split_into" not in v}
    split = {e for group in cfg.get("split", []) for e in group}
    configured = {e for group in cfg.get("merge", []) + cfg.get("split", []) for e in group} | set(cfg.get("names", {}))
    unknown = sorted(configured - set(entries) - set(cfg.get("exclude", {})))
    if unknown:  # a stale id would silently stop a merge from applying
        raise SystemExit(f"config/game_merges.json names entries that don't exist: {unknown}")
    missing_excluded = sorted(set(cfg.get("exclude", {})) - set(entries))
    if missing_excluded:
        raise SystemExit(f"config/game_merges.json excludes entries that don't exist: {missing_excluded}")
    for eid in cfg.get("exclude", {}):  # apps, not games
        entries.pop(eid)

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
        if not days and not any(e["earned"] or e["minutes"] for e in es):
            continue  # owned or launched, with no unlocks, play time, or dated activity
        name = next((cfg["names"][i] for i in ids if i in cfg.get("names", {})), None) \
            or display_name([{**entries[i], "id": i} for i in ids])
        game_id = re.sub(r"[^a-z0-9]+", "-", key(name)).strip("-") or min(ids)
        mins = [e["minutes"] for e in es if e["minutes"]]
        rank = {"switch": 0, "psn": 1, "xbox": 2, "psn-played": 3, "miiverse": 4, "steam": 5}
        arts = sorted((rank[i.split(":")[0]], entries[i]["art"]) for i in ids if entries[i].get("art"))
        games.append({
            "id": game_id, "name": name, "art": arts[0][1] if arts else None,
            "first": days[0] if days else None, "last": days[-1] if days else None, "days": days,
            # Only entries with activity count as platforms played: owning DOOM (2016) on Steam
            # without playing it doesn't make Steam a platform for DOOM
            "families": sorted({e["family"] for e in es if e["days"] or e["earned"] or e["minutes"]}),
            "days_by_family": {f: sorted({d for e in es if e["family"] == f for d in e["days"]})
                               for f in sorted({e["family"] for e in es if e["days"]})},
            "hours": round(sum(mins) / 60, 1) if mins else None,
            "hours_estimated": any(e.get("estimated") for e in es),
            "estimated_from": sorted({s for e in es for s in e.get("estimated_from", [])}),
            "sessions": sum(e.get("sessions") or 0 for e in es) or None,
            "entries": sorted(({"id": i, **{k: v for k, v in entries[i].items() if k != "days"},
                                "name": display(entries[i]["name"]),
                                "first": min(entries[i]["days"], default=None),
                                "last": max(entries[i]["days"], default=None)} for i in ids),
                              key=lambda x: (x["first"] or "9", x["id"])),
        })
    # Unique ids (two different games can share a key-derived slug only through a split)
    seen = defaultdict(int)
    for row in sorted(games, key=lambda r: r["first"] or ""):
        seen[row["id"]] += 1
        if seen[row["id"]] > 1:
            row["id"] += f"-{seen[row['id']]}"
    games.sort(key=lambda r: (r["last"] or "", r["name"]), reverse=True)

    shown = {e["id"] for row in games for e in row["entries"]}
    lost = sorted(set(cfg.get("names", {})) - shown)
    if lost:  # a rename keyed to an entry that isn't in any row would silently do nothing
        raise SystemExit(f"config/game_merges.json renames entries that aren't on the page: {lost}")
    entry_game = {e["id"]: row["id"] for row in games for e in row["entries"]}
    for u in unlocks:
        u["game"] = entry_game.get(u["entry"])
        u["name"] = clean(u["name"] or "")
    unlocks = [u for u in unlocks if u["game"]]
    # Each trophy list's running count of unlocks at the end of every year it had one (dated
    # unlocks only); the Timeline ranks a year's "Most completed" by that count over the total
    by_year = defaultdict(lambda: defaultdict(int))
    for u in unlocks:
        if u["earned"]:
            by_year[u["entry"]][u["earned"][:4]] += 1
    # A trophy list whose platinum is earned, with its date (PlayStation; Platinum pills on the
    # Games tab, and on the Timeline from that year on)
    platinum = {u["entry"]: u["earned"][:10] for u in unlocks if u["earned"] and u.get("kind") == "platinum"}
    for row in games:
        for e in row["entries"]:
            if e["id"] in platinum:
                e["platinum"] = platinum[e["id"]]  # the day it was earned
            if e.get("total") and by_year.get(e["id"]):
                run, e["earned_by_year"] = 0, {}
                for y in sorted(by_year[e["id"]]):
                    run += by_year[e["id"]][y]
                    e["earned_by_year"][y] = run
    unlocks.sort(key=lambda u: (u["earned"] or "", u["game"], u["name"]), reverse=True)

    (DATA / "games.json").write_text(json.dumps(games, indent=1, ensure_ascii=False) + "\n")
    (DATA / "unlocks.json").write_text(json.dumps(unlocks, indent=1, ensure_ascii=False) + "\n")
    multi = sum(1 for r in games if len(r["families"]) > 1)
    print(f"games: {len(games)} rows from {len(entries)} entries ({multi} on more than one platform family); "
          f"{len(unlocks)} unlocks")


if __name__ == "__main__":
    build()
