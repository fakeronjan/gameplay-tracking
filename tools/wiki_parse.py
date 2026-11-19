"""Read a Wikipedia video game infobox's release field (used by wiki_release_dates.py).

Returns the NA (or worldwide) dates in the order the infobox lists them. The infobox lists the
original platform first, so the first date is the game's original North American release;
"earliest" would pick a later re-release that happens to be dated earlier, like Super Mario
Bros. 3's 1989 PlayChoice-10 arcade version ahead of its 1990 NES launch.
"""

import re

MONTHS = "January February March April May June July August September October November December".split()
REGION_OK = {"NA", "WW", "US", "INT", "NORTH AMERICA", "WORLDWIDE"}
RELEASE_TEMPLATES = {"video game release", "vgrelease", "vgrtbl", "vg release"}


def templates(text, names):
    """Each {{name|...}} in text (any of names) with nesting respected: its arguments are split at
    its own pipes, not the pipes of templates or links inside it."""
    out, i = [], 0
    while True:
        i = text.find("{{", i)
        if i < 0:
            return out
        head = re.match(r"\{\{\s*([^|}]+)", text[i:])
        name = head.group(1).strip().lower() if head else ""
        depth, j = 0, i
        while j < len(text):
            two = text[j:j + 2]
            if two in ("{{", "[["):
                depth += 1
                j += 2
                continue
            if two in ("}}", "]]"):
                depth -= 1
                j += 2
                if depth == 0:
                    break
                continue
            j += 1
        if name in names:
            body, args, d, cur, k = text[i + 2:j - 2], [], 0, "", 0
            while k < len(body):
                two = body[k:k + 2]
                if two in ("{{", "[["):
                    d += 1
                    cur += two
                    k += 2
                    continue
                if two in ("}}", "]]"):
                    d -= 1
                    cur += two
                    k += 2
                    continue
                if body[k] == "|" and d == 0:
                    args.append(cur)
                    cur = ""
                    k += 1
                    continue
                cur += body[k]
                k += 1
            args.append(cur)
            out.append((i, args[1:]))
            i = j
        else:
            i += 2


def plain(s):
    """Wikitext to plain words: links become their labels, footnotes go, other templates become
    their last argument ({{Abbr|c.|circa}} -> circa, {{nobold|X}} -> X)."""
    for _ in range(5):
        s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", s)
        s = re.sub(r"\{\{\s*(?:efn|refn|sfn|cn|citation needed)\b[^{}]*\}\}", "", s, flags=re.I)
        s = re.sub(r"\{\{[^{}|]*\|(?:[^{}]*\|)?([^{}|]*)\}\}", r"\1", s)
    s = s.replace("'''", "").replace("''", "")
    return re.sub(r"<[^>]+>", "", s)


def parse_date(s):
    pats = [
        (r"(?:" + "|".join(MONTHS) + r")\s+\d{1,2},\s+\d{4}", "%B %d, %Y", "day"),
        (r"\d{1,2}\s+(?:" + "|".join(MONTHS) + r")\s+\d{4}", "%d %B %Y", "day"),
        (r"(?:" + "|".join(MONTHS) + r")\s+\d{4}", "%B %Y", "month"),
        (r"\b(?:19[7-9]\d|20[0-3]\d)\b", "%Y", "year"),
    ]
    from datetime import datetime
    for rx, fmt, prec in pats:
        m = re.search(rx, s)
        if m:
            return datetime.strptime(m.group(0), fmt).date().isoformat(), prec
    return None


def release_field(wikitext):
    wikitext = re.sub(r"<ref[^>]*/>", "", wikitext)
    wikitext = re.sub(r"<ref[^>]*>.*?</ref>", "", wikitext, flags=re.S)
    wikitext = re.sub(r"<!--.*?-->", "", wikitext, flags=re.S)
    m = re.search(r"\|\s*released?\s*=(.*?)(?:\n\s*\|\s*[a-z_ ]+=|\n\}\})", wikitext, re.S | re.I)
    return m.group(1) if m else ""


def na_dates(wikitext):
    """NA or worldwide dates, in infobox order (first = the original platform's)."""
    field = release_field(wikitext)
    if not field:
        return []
    out = []
    for _, args in templates(field, RELEASE_TEMPLATES):
        for code, val in zip(args[0::2], args[1::2]):
            regions = {x.strip().upper() for x in re.split(r"[/,]", plain(code))}
            if regions & REGION_OK:
                d = parse_date(plain(val))
                if d:
                    out.append(d)
    if not out and not re.search(r"\b(JP|JPN|EU|PAL|AU|AUS|KOR)\b", plain(field)):
        # A plain list with no regions named (Hades): a worldwide release
        flat = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", field).replace("{{", "|").replace("}}", "|")
        for line in re.split(r"<br\s*/?>|\n|\|", flat):
            d = parse_date(line)
            if d:
                out.append(d)
    return out
