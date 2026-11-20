"""One-time import of Meta Quest play days from Meta's data export.

Input: local/meta_export/extracted/ (Ronjan's 2026-11-20 "Download your information"
export, HTML format; never committed). Output: docs/data/meta.json.

Which games, and what counts as a play day, is set in config/meta_games.json:
  - the day each game's cloud save was first created (your_apps_and_content/cloud_backups.html)
  - Beat Saber only: the first visit to each level (worlds/worlds_visited.html, matched on app id)
Export times are US Pacific (the page labels them UTC, but the <time> tag shows 11:24 AM
next to 19:24Z); days are taken in Eastern time like the other sources.

    .venv/bin/python tools/build_meta.py
"""

import json
import re
import html
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent.parent
EXPORT = HERE / "local" / "meta_export" / "extracted"
CONFIG = HERE / "config" / "meta_games.json"
OUT = HERE / "docs" / "data" / "meta.json"
PT, ET = ZoneInfo("America/Los_Angeles"), ZoneInfo("America/New_York")


def et_day(stamp):
    t = datetime.strptime(stamp.strip(), "%b %d, %Y %I:%M %p").replace(tzinfo=PT)
    return t.astimezone(ET).date().isoformat()


def norm(name):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"[™®©]", "", name).lower()).strip()


def records(rel):
    """Each export record as {field: value, '_time': the record's footer timestamp}."""
    page = (EXPORT / rel).read_text(encoding="utf-8")
    page = page[page.find("<main"):]
    parts = re.split(r'<footer[^>]*><div class="_a72d">', page)
    out = []
    for body, after in zip(parts[:-1], parts[1:]):
        rows = re.findall(r'<td class="_a6_q">(.*?)</td><td class="_2piu _a6_r">(.*?)</td>', body[body.rfind("<table"):], re.S)
        rec = {html.unescape(re.sub("<[^>]+>", "", k)): html.unescape(re.sub("<[^>]+>", " ", v)).strip() for k, v in rows}
        rec["_time"] = after[:after.find("<")]
        rec["_url"] = (re.search(r'/vr/(\d+)/', body[body.rfind("<table"):]) or [None, None])[1]
        out.append(rec)
    return out


def wiki_art(title):
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    req = urllib.request.Request(url, headers={"User-Agent": "gameplay-tracking/1.0 (personal site)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    src = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
    return src.split("?")[0] if src else None


def main():
    cfg = json.loads(CONFIG.read_text())
    old = json.loads(OUT.read_text())["games"] if OUT.exists() else {}
    backups = {norm(r["App name"]): r["_time"] for r in records("your_apps_and_content/cloud_backups.html") if r.get("App name")}
    worlds = records("worlds/worlds_visited.html")
    games, missing = {}, []
    for g in cfg["games"]:
        created = backups.get(norm(g["export_name"]))
        if not created:
            missing.append(g["export_name"])
            continue
        days = {et_day(created): ["first cloud save"]}
        if g.get("app_id"):
            for w in worlds:
                if w["_url"] == g["app_id"]:
                    days.setdefault(et_day(w["_time"]), []).append(f"first opened {w.get('Name')}")
        art = (old.get(g["name"], {}).get("art") or wiki_art(g["wiki"]) or "").split("?")[0] or None
        games[g["name"]] = {"days": sorted(days), "evidence": {d: v for d, v in sorted(days.items())}, "art": art}
    if missing:
        raise SystemExit("No cloud save in the export for: " + ", ".join(missing))
    OUT.write_text(json.dumps({"note": "Meta Quest: first cloud-save day per game, plus Beat Saber level first-visit days. No hours.",
                               "games": games}, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    for n, g in games.items():
        print(f"{n:30} {len(g['days'])} days  {', '.join(g['days'])}  art {'yes' if g['art'] else 'NO'}")


if __name__ == "__main__":
    main()
