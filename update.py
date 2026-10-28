"""Daily refresh of PlayStation and Steam gameplay data into docs/data/.

Incremental: a game is refetched only when the platform says it changed since
the last run (PSN trophy title lastUpdatedDateTime, Steam rtime_last_played).
Play-time totals that moved since the last run are appended to
playtime_log.json, which is the only source of day-by-day hours.

Secrets come from the environment (GitHub Actions secrets in CI):
    PSN_NPSSO, STEAM_API_KEY
Locally, missing variables fall back to the macOS Keychain entries
psn-npsso and steam-api-key.

    python update.py            # both platforms
    python update.py psn        # one platform
    python update.py --seed-psn local/psn_raw   # build psn.json from a local raw dump
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "docs" / "data"
TROPHY = "https://m.np.playstation.com/api/trophy/v1"
GAMELIST = "https://m.np.playstation.com/api/gamelist/v2"
STEAM = "https://api.steampowered.com"
STEAM_ID = "76561198018644815"
NOW = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def secret(env, keychain):
    if os.environ.get(env):
        return os.environ[env].strip()
    return subprocess.run(["security", "find-generic-password", "-a", os.environ["USER"], "-s", keychain, "-w"],
                          capture_output=True, text=True, check=True).stdout.strip()


def load(name, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


def save(name, data):
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n")


def minutes(play_duration):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)(?:\.\d+)?S)?", play_duration or "")
    if not m:
        return 0
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 60 + mi + (1 if s >= 30 else 0)


def log_playtime(log, platform, game_id, name, before, after):
    if before is not None and after > before:
        log.append({"time": NOW, "platform": platform, "id": game_id, "name": name,
                    "minutes_total": after, "minutes_delta": after - before})


# ---------------------------------------------------------------- PlayStation

def psn_title(title, definitions, earned):
    """One trophy title in the published shape: summary plus earned trophies."""
    defs = {(d.get("trophyGroupId", "default"), d["trophyId"]): d for d in definitions.get("trophies", [])}
    trophies = []
    for e in earned.get("trophies", []):
        if not e.get("earned"):
            continue
        d = defs.get((e.get("trophyGroupId", "default"), e["trophyId"]), {})
        trophies.append({
            "id": e["trophyId"], "group": e.get("trophyGroupId", "default"),
            "name": d.get("trophyName"), "detail": d.get("trophyDetail"),
            "type": e["trophyType"], "earned": e["earnedDateTime"],
            "rarity": float(e["trophyEarnedRate"]) if e.get("trophyEarnedRate") else None,
            "icon": d.get("trophyIconUrl"),
        })
    trophies.sort(key=lambda t: (t["earned"], t["group"], t["id"]))
    return {
        "name": title["trophyTitleName"], "platform": title["trophyTitlePlatform"],
        "service": title["npServiceName"], "icon": title.get("trophyTitleIconUrl"),
        "defined": title["definedTrophies"], "earned_counts": title["earnedTrophies"],
        "progress": title["progress"], "last_updated": title["lastUpdatedDateTime"],
        "trophies": trophies,
    }


def psn_played(raw):
    return {p["titleId"]: {
        "name": p["name"], "category": p["category"], "image": p.get("imageUrl"),
        "concept_id": (p.get("concept") or {}).get("id"),
        "play_count": p.get("playCount"), "first_played": p.get("firstPlayedDateTime"),
        "last_played": p.get("lastPlayedDateTime"), "minutes": minutes(p.get("playDuration")),
    } for p in raw}


def psn_paged(auth, url, key, extra=None):
    items, offset = [], 0
    while True:
        resp = auth.get(url=url, params={"limit": 200, "offset": offset, **(extra or {})}).json()
        items += resp.get(key, [])
        offset += 200
        if offset >= resp.get("totalItemCount", 0) or not resp.get(key):
            return items


def seed_psn(raw_dir):
    raw = Path(raw_dir)
    titles = {}
    for f in sorted((raw / "titles").glob("*.json")):
        d = json.loads(f.read_text())
        titles[d["title"]["npCommunicationId"]] = psn_title(d["title"], d["definitions"], d["earned"])
    played = psn_played(json.loads((raw / "played_titles.json").read_text()))
    summary = json.loads((raw / "trophy_summary.json").read_text())
    summary.pop("accountId", None)
    save("psn.json", {"updated": NOW, "summary": summary, "titles": titles, "played": played})
    print(f"psn: seeded {len(titles)} trophy titles, {len(played)} played titles")


def update_psn(log):
    from psnawp_api import PSNAWP

    old = load("psn.json", {"titles": {}, "played": {}})
    auth = PSNAWP(secret("PSN_NPSSO", "psn-npsso")).authenticator

    summary = auth.get(url=f"{TROPHY}/users/me/trophySummary").json()
    summary.pop("accountId", None)
    titles = dict(old["titles"])
    changed = 0
    for t in psn_paged(auth, f"{TROPHY}/users/me/trophyTitles", "trophyTitles"):
        cid, svc = t["npCommunicationId"], t["npServiceName"]
        prev = titles.get(cid)
        if prev and prev["last_updated"] == t["lastUpdatedDateTime"]:
            continue
        defs = auth.get(url=f"{TROPHY}/npCommunicationIds/{cid}/trophyGroups/all/trophies",
                        params={"npServiceName": svc}).json()
        earned = auth.get(url=f"{TROPHY}/users/me/npCommunicationIds/{cid}/trophyGroups/all/trophies",
                          params={"npServiceName": svc}).json()
        titles[cid] = psn_title(t, defs, earned)
        changed += 1

    played = psn_played(psn_paged(auth, f"{GAMELIST}/users/me/titles", "titles",
                                  {"categories": "ps4_game,ps5_native_game"}))
    for tid, p in played.items():
        # A game new to the list counts from 0; with no previous file at all there's no baseline yet
        before = old["played"].get(tid, {}).get("minutes", 0) if old["played"] else None
        log_playtime(log, "psn", tid, p["name"], before, p["minutes"])

    save("psn.json", {"updated": NOW, "summary": summary, "titles": titles, "played": played})
    print(f"psn: {len(titles)} trophy titles ({changed} refetched), {len(played)} played titles")


# ---------------------------------------------------------------------- Steam

def steam_get(path, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(f"{STEAM}/{path}?{query}", timeout=30))
        except urllib.error.HTTPError as e:
            if e.code == 400:  # "Requested app has no stats"
                return None
            if attempt == 2:
                print(f"steam: {path} {params.get('appid')} failed with HTTP {e.code}")
                return None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(5)


def update_steam(log):
    key = secret("STEAM_API_KEY", "steam-api-key")
    old = load("steam.json", {"games": {}})
    owned = steam_get("IPlayerService/GetOwnedGames/v1/", key=key, steamid=STEAM_ID,
                      include_appinfo=1, include_played_free_games=1)["response"]["games"]
    games, refetched = {}, 0
    for g in owned:
        appid = str(g["appid"])
        prev = old["games"].get(appid, {})
        game = {
            "name": g["name"], "icon": g.get("img_icon_url"), "minutes": g["playtime_forever"],
            "last_played": (datetime.fromtimestamp(g["rtime_last_played"], timezone.utc).isoformat().replace("+00:00", "Z")
                            if g.get("rtime_last_played") else None),
            "achievements": prev.get("achievements"),
        }
        log_playtime(log, "steam", appid, g["name"], prev.get("minutes", 0) if old["games"] else None, game["minutes"])
        if "achievements" not in prev or prev.get("last_played") != game["last_played"]:
            game["achievements"] = steam_achievements(key, appid)
            refetched += 1
        games[appid] = game
    save("steam.json", {"updated": NOW, "games": games})
    print(f"steam: {len(games)} games ({refetched} achievement lists refetched)")


def steam_achievements(key, appid):
    """Earned achievements with global rarity, or None when the game has none."""
    d = steam_get("ISteamUserStats/GetPlayerAchievements/v1/", key=key, steamid=STEAM_ID, appid=appid, l="english")
    ach = (d or {}).get("playerstats", {}).get("achievements")
    if not ach:
        return None
    pct = steam_get("ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/", gameid=appid) or {}
    rarity = {a["name"]: float(a["percent"]) for a in pct.get("achievementpercentages", {}).get("achievements", [])}
    earned = [{
        "id": a["apiname"], "name": a.get("name"), "detail": a.get("description"),
        "earned": datetime.fromtimestamp(a["unlocktime"], timezone.utc).isoformat().replace("+00:00", "Z"),
        "rarity": round(rarity[a["apiname"]], 1) if a["apiname"] in rarity else None,
    } for a in ach if a["achieved"]]
    earned.sort(key=lambda a: (a["earned"], a["id"]))
    return {"total": len(ach), "earned": earned}


def main():
    args = sys.argv[1:]
    if args[:1] == ["--seed-psn"]:
        seed_psn(args[1])
        return
    platforms = args or ["psn", "steam"]
    log = load("playtime_log.json", [])
    failed = []
    for name, fn in (("psn", update_psn), ("steam", update_steam)):
        if name not in platforms:
            continue
        try:
            fn(log)
        except Exception as e:  # one platform failing shouldn't block the other
            print(f"{name}: FAILED: {e!r}")
            failed.append(name)
    save("playtime_log.json", log)
    status = load("status.json", {})
    status.update({"updated": NOW, "failed": failed,
                   "psn_npsso_expires": os.environ.get("PSN_NPSSO_EXPIRES", status.get("psn_npsso_expires"))})
    for name in platforms:
        if name not in failed:
            status[f"{name}_ok"] = NOW
    save("status.json", status)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
