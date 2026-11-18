"""Zelda Notes medals and milestones, read from Ronjan's screenshots of the Nintendo Switch App.

Zelda Notes has no export, and the only automated route goes through a third-party token
service with the main Nintendo account (vetted and turned down 2026-11-18). So Ronjan
screenshots each medal page (scrolled to the first "Keep at it...") and each Photo Studio
milestone, and this reads them with macOS Vision (tools/zn_ocr.swift).

Input: local/zelda_notes/raw/*.png (moved out of iCloud Photos, named by capture time).
Output:
  docs/data/zelda_notes.json      medals (name, stat, value, tiers with threshold and earned day)
                                  and milestones (stat, value, local time), for build_games.py
  local/zelda_notes/parsed.json   the same plus the source screenshot and picture crop for each
                                  milestone, for build_gallery.py (stays local: it has file paths)

Repeat captures of a medal or milestone merge, so re-capturing everything only adds what's new.

    python build_zelda_notes.py
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
RAW = HERE / "local" / "zelda_notes" / "raw"
CACHE = HERE / "local" / "zelda_notes" / "ocr_cache.json"
PARSED = HERE / "local" / "zelda_notes" / "parsed.json"
OUT = HERE / "docs" / "data" / "zelda_notes.json"
GAME_ENTRY = "nintendo:0400486024dec000"  # Ocarina of Time (Switch 2)
TIERS = ["Bronze", "Silver", "Gold", "Master"]
NAME_FIXES = {"quest Challenger": "Quest Challenger"}  # text recognition drops the capital Q


def ocr(paths):
    """Positional OCR for every screenshot, cached by file name and size."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [p for p in paths if cache.get(p.name, {}).get("size") != p.stat().st_size]
    if todo:
        lst = HERE / "local" / "zelda_notes" / "ocr_todo.txt"
        lst.write_text("\n".join(str(p) for p in todo) + "\n")
        res = subprocess.run(["swift", str(HERE / "tools" / "zn_ocr.swift"), str(lst)],
                             capture_output=True, text=True, check=True)
        for path, boxes in json.loads(res.stdout).items():
            p = Path(path)
            cache[p.name] = {"size": p.stat().st_size, "boxes": boxes}
        lst.unlink()
        CACHE.write_text(json.dumps(cache, sort_keys=True))
    return {p: cache[p.name]["boxes"] for p in paths}


def rows(boxes):
    return sorted(boxes, key=lambda b: (b["y"], b["x"]))


def right_of(boxes, y, tol=0.022):
    """The value column: text right of center on the same row as a label at y."""
    hits = sorted((b for b in boxes if b["x"] > 0.45 and abs(b["y"] - y) < tol), key=lambda b: b["x"])
    return " ".join(b["t"] for b in hits).strip() or None


def parse_medal(boxes):
    left = [b for b in rows(boxes) if b["x"] < 0.45]
    text = " ".join(b["t"] for b in left)
    # A second capture of a tall page starts mid-sentence ("your People Spoken To stat")
    m = re.search(r"(?:Earned by increasing )?your (.+?) stat\b", text)
    if not m:
        return None
    stat = m.group(1).strip()
    first = next(i for i, b in enumerate(left) if b["t"].startswith(("Earned by", "your ")))
    head = [b["t"] for b in left[:first] if not re.fullmatch(r"\d+:\d+", b["t"])]
    name = current = None
    if head and head[-1] in TIERS:
        current, head = head[-1], head[:-1]
    if head:
        name = " ".join(head).strip()
        name = NAME_FIXES.get(name, name)
    medal = {"stat": stat, "name": name, "current": current, "value": None, "tiers": {}}
    label = next((b for b in left if b["t"] == stat), None)
    if label:
        medal["value"] = right_of(boxes, label["y"])
    for b in left:
        if b["t"] in TIERS and 0.2 < b["x"] < 0.3:
            status = next((s for s in left if 0.2 < s["x"] < 0.3 and 0.015 < s["y"] - b["y"] < 0.06), None)
            if status is None:
                continue  # cut off at the bottom of the screenshot; the next capture has it
            earned = re.search(r"Earned on (\d+)/(\d+)/(\d{4})", status["t"])
            threshold = right_of(boxes, b["y"], tol=0.02)
            medal["tiers"][b["t"]] = {
                "threshold": None if threshold in (None, "???") else threshold,
                "earned": f"{earned.group(3)}-{int(earned.group(1)):02d}-{int(earned.group(2)):02d}" if earned else None,
                "label_y": b["y"],
            }
    return medal


def parse_milestone(boxes, path):
    lines = rows(boxes)
    for i, b in enumerate(lines):
        m = re.search(r"Milestone reached: (\d+)/(\d+)/(\d{4}),? (\d+):(\d+)", b["t"])
        if not m:
            continue
        mo, d, y, hh, mm = map(int, m.groups())
        stat_line = next((x for x in lines[i + 1:] if ":" in x["t"]), None)
        if not stat_line:
            return None
        stat, value = [s.strip() for s in stat_line["t"].rsplit(":", 1)]
        return {"stat": stat, "value": value, "time": datetime(y, mo, d, hh, mm).isoformat(timespec="minutes"),
                "src": str(path), "crop": picture_box(path, b["y"])}
    return None


def picture_box(path, text_top):
    """The rendered picture above the date line. It always sits at the same spot: a 16:9 panel,
    1144 px wide on a 1398 px screen, ending 47 px above the date line (measured 11/18 on 31
    captures). Scaled to the screenshot's width so a different phone still lines up."""
    w, h = Image.open(path).size
    k = w / 1398
    bottom = round(text_top * h - 47 * k)
    width = round(1144 * k)
    return [0, bottom - round(width * 9 / 16), width, bottom]


def save_badge(stat, tier, badge):
    """A tier's badge, cropped from its row on the medal page (left of the tier name), saved as
    the unlock icon the way fetch_images.py stores downloaded ones (64 px webp)."""
    slug = re.sub(r"[^a-z0-9]+", "-", stat.lower()).strip("-")
    rel = f"img/u/zn-{slug}-{tier.lower()}.webp"
    out = HERE / "docs" / rel
    im = Image.open(badge["src"]).convert("RGBA")
    w, h = im.size
    cx, cy, side = 0.14 * w, badge["label_y"] * h + 0.032 * h, 0.12 * w
    crop = im.crop((round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2)))
    crop.thumbnail((64, 64))
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out, "WEBP", quality=88)
    return rel


def main():
    paths = sorted(RAW.glob("*.png"))
    boxes = ocr(paths)
    medals, milestones = {}, {}
    for p in paths:  # oldest capture first, so later captures win on current value and tier
        b = boxes[p]
        text = " ".join(x["t"] for x in b)
        if "Milestone reached" in text:
            ms = parse_milestone(b, p)
            if ms:
                milestones.setdefault((ms["stat"], ms["value"], ms["time"]), ms)
            continue
        md = parse_medal(b)
        if not md:
            continue  # the milestone gallery overview and anything else
        for info in md["tiers"].values():
            info["src"] = str(p)
        cur = medals.setdefault(md["stat"], {"stat": md["stat"], "name": None, "current": None, "value": None, "tiers": {}})
        for k in ("name", "current", "value"):
            if md[k]:
                cur[k] = md[k]
        for tier, info in md["tiers"].items():
            old = cur["tiers"].get(tier, {})
            cur["tiers"][tier] = {"threshold": info["threshold"] or old.get("threshold"),
                                  "earned": info["earned"] or old.get("earned")}
            if info["earned"]:  # where to crop this tier's badge from
                cur["tiers"][tier]["badge"] = {"src": info["src"], "label_y": info["label_y"]}

    medal_list = []
    problems = []
    for stat, m in sorted(medals.items()):
        if m["name"] in (None, "???"):
            m["name"] = None  # hidden until the first tier is earned
        earned = [t for t in TIERS if (m["tiers"].get(t) or {}).get("earned")]
        if earned and not m["name"]:
            problems.append(f"medal for {stat!r} has earned tiers but no name was read")
        if m["current"] and earned and m["current"] != earned[-1]:
            problems.append(f"{stat}: page says {m['current']} but the last earned tier read is {earned[-1]}")
        tiers = []
        for t in TIERS:
            info = m["tiers"].get(t, {"threshold": None, "earned": None})
            icon = save_badge(stat, t, info["badge"]) if info.get("badge") else None
            tiers.append({"tier": t, "threshold": info["threshold"], "earned": info["earned"], "icon": icon})
        medal_list.append({"name": m["name"], "stat": stat, "value": m["value"], "tiers": tiers})
    if problems:
        raise SystemExit("Zelda Notes screenshots need another look:\n  " + "\n  ".join(problems))
    ms_list = sorted(milestones.values(), key=lambda x: x["time"], reverse=True)
    captured = max(p.stem[3:13] for p in paths) if paths else None

    public = {"game_entry": GAME_ENTRY, "captured": captured,
              "medals": medal_list,
              "milestones": [{k: v for k, v in ms.items() if k in ("stat", "value", "time")} for ms in ms_list]}
    OUT.write_text(json.dumps(public, indent=1, ensure_ascii=False) + "\n")
    PARSED.write_text(json.dumps({**public, "milestones": ms_list}, indent=1, ensure_ascii=False) + "\n")
    tiers = sum(1 for m in medal_list for t in m["tiers"] if t["earned"])
    print(f"zelda notes: {len(medal_list)} medals ({sum(1 for m in medal_list if m['name'])} named), "
          f"{tiers} of {4 * len(medal_list)} tiers earned, {len(ms_list)} milestones")


if __name__ == "__main__":
    main()
