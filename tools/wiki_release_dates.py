"""North American release dates from each game's Wikipedia infobox (local/igdb/wiki.json).

A third source beside IGDB and the stores (Ronjan 2026-11-18: "I've been finding these pretty
easily" on Wikipedia). Reads the infobox's release field and takes the earliest NA (or
worldwide) date. Cached; anything it can't read is left blank, not guessed.

    .venv/bin/python tools/wiki_release_dates.py <row-id> ...   (default: the review list)
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "local" / "igdb" / "wiki.json"
UA = {"User-Agent": "gameplay-tracking/1.0 (personal game-history site; release-date lookup)"}
MONTHS = "January February March April May June July August September October November December".split()


def api(**p):
    p.update(format="json", formatversion="2", maxlag="5")
    for attempt in range(6):
        time.sleep(1.2 + attempt * 3)  # gentle: Wikipedia throttles fast anonymous clients
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(p), headers=UA)))
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    raise RuntimeError("Wikipedia kept rate-limiting")


def parse_date(s):
    s = re.sub(r"\[\[|\]\]|<[^>]+>|\{\{[^}]*\}\}", "", s).strip(" ,;|")
    for fmt in ("%B %d, %Y", "%d %B %Y", "%B %Y", "%Y"):
        m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}" if fmt == "%B %d, %Y"
                      else r"\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\s+\d{4}" if fmt == "%d %B %Y"
                      else r"(?:" + "|".join(MONTHS) + r")\s+\d{4}" if fmt == "%B %Y" else r"\b(19[7-9]\d|20[0-3]\d)\b", s)
        if m:
            d = datetime.strptime(m.group(0), fmt).date()
            return d.isoformat(), {"%B %d, %Y": "day", "%d %B %Y": "day", "%B %Y": "month", "%Y": "year"}[fmt]
    return None


from wiki_parse import na_dates  # noqa: E402  (infobox reading lives there)


def lookup(name, year=None, alt=None):
    """The game's own article, by exact title the way a person finds it: the name, then
    "Name (video game)", then "Name (YEAR video game)", following redirects (one request for
    all of them). Search only as a last resort, and only when the article title matches."""
    base = re.sub(r"\s\((?!\d{4}\))[^)]+\)$", "", name.split(" + ")[0])
    m = re.search(r"\((\d{4})\)$", base)
    if m:
        year, base = m.group(1), base[: m.start()].strip()
    titles = [base, f"{base} (video game)"] + ([f"{base} ({year} video game)"] if year else []) + ([alt] if alt and alt != base else [])
    res = api(action="query", titles="|".join(titles), redirects=1, prop="revisions", rvprop="content", rvslots="main")
    pages = {p["title"]: p for p in res["query"].get("pages", []) if not p.get("missing")}
    # map each tried title to the page it landed on (after normalizing and redirects)
    hop = {}
    for kind in ("normalized", "redirects"):
        for x in res["query"].get(kind, []):
            hop[x["from"]] = x["to"]
    def page_for(t):
        seen = 0
        while t in hop and seen < 3:
            t, seen = hop[t], seen + 1
        return pages.get(t)
    for t in ([f"{base} ({year} video game)"] if year else []) + [f"{base} (video game)", base] + ([alt] if alt else []):
        pg = page_for(t)
        if not pg:
            continue
        text = pg["revisions"][0]["slots"]["main"]["content"]
        if "infobox video game" not in text.lower():
            continue
        return {"title": pg["title"], "dates": na_dates(text), "how": "exact title"}
    return {"title": None, "dates": [], "how": "no article by exact title"}


def main():
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    ids = sys.argv[1:] or list(json.loads((HERE / "local/igdb/decisions.json").read_text())["review"])
    games = {r["id"]: r for r in json.loads((HERE / "docs/data/games.json").read_text())}
    rel = json.loads((HERE / "config/release_dates.json").read_text())["dates"]
    igdb = json.loads((HERE / "local/igdb/matches.json").read_text())
    for i in ids:
        if i not in cache or cache[i].get("error") or cache[i].get("how") != "exact title":
            try:
                yr = (rel.get(i, {}).get("date") or "")[:4] or None
                pick = (igdb.get(i) or {}).get("pick") or {}
                cache[i] = lookup(games[i]["name"], yr, pick.get("name"))
            except Exception as e:
                cache[i] = {"title": None, "dates": [], "error": repr(e)}
            OUT.write_text(json.dumps(cache, indent=1))
    OUT.write_text(json.dumps(cache, indent=1))
    print(sum(1 for i in ids if cache[i]["dates"]), "of", len(ids), "have an NA date on Wikipedia")


if __name__ == "__main__":
    main()
