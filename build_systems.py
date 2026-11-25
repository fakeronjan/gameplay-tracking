"""Systems tab data: one card per system family, built from games.json.

Inputs: config/systems.json (the systems, their units and photos), config/rereleases.json
(older systems' games played on later hardware), docs/data/games.json. Output:
docs/data/systems.json. Runs after build_games.py, daily in the workflow.

    python build_systems.py

Rules (Ronjan, 2026-11-20):
  - A unit's first-played date is its purchase date, or the model's US launch date when it was
    bought before launch (a pre-order). A system's first played is the earliest of its units and
    its first day of recorded play; a config "first_played" overrides it (null = unknown).
  - Last played: the latest play of the system's games anywhere (see below). Formerly "Still have one" / the last day of play recorded on the
    hardware; else the latest dated sale, gift, or trade.
  - Hours are the headline number. Play on the hardware and play of its games elsewhere are
    separate; the same hour can count on both a Wii U card and the SNES card.
  - Xbox One vs Series X|S is split at 11/9/2020 (Xbox doesn't record which console was used).
"""

import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "docs" / "data"
CONFIG = HERE / "config"

# Re-releases where only some of a game's records are the old version
ENTRY_FILTERS = {
    ("PlayStation 2", "Grand Theft Auto: Vice City"): lambda e: e["id"].startswith(("psn-played:CUSA03509", "psn:NPWR09341")),
    ("Xbox (original)", "Star Wars: Knights of the Old Republic"): lambda e: e["family"] == "Xbox",
}


def xbox_backcompat(e):
    """A 360 game's record on the Xbox One / Series account (not a Legendary Edition part)."""
    return e.get("platform") == "Xbox" and "#" not in e["id"]


def d(s):
    return date.fromisoformat(s)


def split_minutes(e, start, end):
    """Minutes of an Xbox record that fall in [start, end] (ISO dates or None), with the first
    and last days of that part. Modeled monthly minutes when the record has them, else spread
    evenly over its first-to-last days."""
    first, last, mins = e.get("first"), e.get("last"), e.get("minutes") or 0
    if not first:
        return 0, None, None
    lo, hi = max(first, start or first), min(last, end or last)
    if lo > hi:
        return 0, None, None
    monthly = e.get("modeled_hours") or {m: v[1] for m, v in (e.get("modeled") or {}).items()}
    daily = e.get("day_minutes") or {}
    if monthly or daily:
        inside = lambda k: (not start or k >= start[:len(k)]) and (not end or k <= end[:len(k)])
        part = sum(v for m, v in monthly.items() if inside(m)) + sum(v for k, v in daily.items() if inside(k))
        whole = (sum(monthly.values()) + sum(daily.values())) or 1
        return mins * part / whole, lo, hi
    span = (d(last) - d(first)).days + 1
    return mins * ((d(hi) - d(lo)).days + 1) / span, lo, hi


def game_rows(picks):
    """picks: [(game, [entries], (start, end) or None)] -> per-game rows and the totals.
    A game can appear more than once (records with different date windows); it gets one row."""
    merged = {}
    for g, es, window in picks:
        merged.setdefault(g["id"], (g, []))[1].extend((e, window) for e in es)
    rows = []
    for g, pairs in merged.values():
        mins, est, first, last, plats = 0, False, None, None, set()
        for e, window in pairs:
            if window:
                m, f, l = split_minutes(e, *window)
            else:
                m, f, l = e.get("minutes") or 0, e.get("first"), e.get("last")
            if not (m or f):
                continue
            mins += m
            est = est or bool(e.get("estimated"))
            first = min(filter(None, [first, f]), default=None)
            last = max(filter(None, [last, l]), default=None)
            plats.add(e.get("platform") or "")
        if not (mins or first):
            continue
        rows.append({"id": g["id"], "name": g["name"], "img": g.get("img"), "hours": round(mins / 60, 1) if mins else None,
                     "est": est, "first": first, "last": last, "family_play": g.get("family_play", False),
                     "on": ", ".join(sorted(p for p in plats if p))})
    rows.sort(key=lambda r: (-(r["hours"] or 0), r["name"]))
    if not rows:
        return None
    hrs = sum(r["hours"] or 0 for r in rows)
    return {"games": len(rows), "hours": round(hrs), "est": any(r["est"] for r in rows),
            "first": min((r["first"] for r in rows if r["first"]), default=None),
            "last": max((r["last"] for r in rows if r["last"]), default=None),
            "top": rows[0]["name"], "top_id": rows[0]["id"], "rows": rows,
            "family_play": any(r["family_play"] for r in rows)}


def main():
    systems = json.loads((CONFIG / "systems.json").read_text())["systems"]
    rereleases = json.loads((CONFIG / "rereleases.json").read_text())["systems"]
    games = json.loads((DATA / "games.json").read_text())
    by_name = {g["name"]: g for g in games}
    out, problems = [], []
    for s in systems:
        hw = s.get("hardware")
        on = None
        if hw:
            window = (hw.get("from"), hw.get("until")) if (hw.get("from") or hw.get("until")) else None
            picks = []
            for g in games:
                for plat in hw["platforms"]:
                    es = [e for e in g["entries"] if e.get("platform") == plat]
                    if es:
                        w = tuple(hw["split"][plat]) if plat in hw.get("split", {}) else window
                        picks.append((g, es, w))
            on = game_rows(picks)
        elsewhere = None
        if s.get("rereleases"):
            picks = []
            for item in rereleases[s["rereleases"]]:
                g = by_name.get(item["game"])
                if not g:
                    problems.append(f"{s['id']}: no game named {item['game']!r}")
                    continue
                es = [e for e in g["entries"] if not e["id"].startswith(("miiverse:", "camera:", "blog:"))]
                f = ENTRY_FILTERS.get((s["rereleases"], g["name"]))
                if s["id"] == "xbox-360":
                    f = xbox_backcompat
                if f:
                    es = [e for e in es if f(e)]
                picks.append((g, es, None))
            elsewhere = game_rows(picks)

        # First played
        if "first_played" in s:
            first = s["first_played"]
        else:
            starts = [max(u["bought"], u.get("launch") or u["bought"]) for u in s["units"] if u.get("bought")]
            if on and on["first"]:
                starts.append(on["first"])
            first = min(starts) if starts else None
        # Last played (Ronjan 2026-11-25): the latest day any of this system's games was played, on its
        # own hardware or anywhere else (a PS4 game on a PS5, SNES games on Switch Online), so a system
        # stays current as long as its games do. Whether a unit is still on hand only shows as the year
        # range ending "now" (have). A system with no recorded play at all falls back to when it went.
        have = any(u.get("have") for u in s["units"])
        played = max(filter(None, [on["last"] if on else None, elsewhere["last"] if elsewhere else None]), default=None)
        if played:
            last = {"kind": "played", "date": played}
        else:
            gone = sorted((u["gone"][1], u["gone"][0]) for u in s["units"] if u.get("gone") and u["gone"][1])
            last = {"kind": gone[-1][1], "date": gone[-1][0]} if gone else None

        out.append({
            "id": s["id"], "name": s["name"], "family": s["family"], "versions": s["versions"],
            "img": f"img/systems/stock-{s['id']}.jpg",
            "photos": [{"img": f"img/systems/photo-{p[0]}.jpg", "caption": p[1], "date": p[2]} for p in s["photos"]],
            "first": first, "launched": s.get("launched"), "last": last, "have": have, "on": on, "elsewhere": elsewhere,
        })
        for p in s["photos"]:
            if not (HERE / "docs" / "img" / "systems" / f"photo-{p[0]}.jpg").exists():
                problems.append(f"{s['id']}: missing photo {p[0]}")
        if not (HERE / "docs" / "img" / "systems" / f"stock-{s['id']}.jpg").exists():
            problems.append(f"{s['id']}: missing stock image")
    if problems:
        raise SystemExit("systems: " + "; ".join(problems))
    (DATA / "systems.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for s in out:
        o, e = s["on"], s["elsewhere"]
        print(f"{s['name']:30} first {s['first'] or '?':10} last {s['last']}  "
              f"on {o['games'] if o else '-'}g/{o['hours'] if o else '-'}h  elsewhere {e['games'] if e else '-'}g/{e['hours'] if e else '-'}h")


if __name__ == "__main__":
    main()
