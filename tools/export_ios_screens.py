"""Copy every iPhone/iPad screenshot out of Photos (full-size originals) for sorting by game.
Read-only on the Photos library: it only exports. Batches never repeat a file name (iOS
restarts IMG_ numbering), and each export is renamed to <capture time>_<id>.<ext> right away.
Writes local/ios_screens/manifest.json (Photos id, capture time, size, original name, file).
Re-runnable: skips anything already exported.

    python tools/export_ios_screens.py
"""
import json, sqlite3, subprocess, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "local" / "ios_screens"
RAW = OUT / "raw"
TMP = OUT / "tmp"
DB = Path.home() / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = con.execute("""select a.ZUUID, a.ZDATECREATED + 978307200, a.ZWIDTH, a.ZHEIGHT, b.ZORIGINALFILENAME
                      from ZASSET a join ZADDITIONALASSETATTRIBUTES b on b.ZASSET = a.Z_PK
                      where a.ZTRASHEDSTATE = 0 and a.ZKINDSUBTYPE = 10 order by a.ZDATECREATED""").fetchall()
man_path = OUT / "manifest.json"
manifest = json.loads(man_path.read_text()) if man_path.exists() else {}
RAW.mkdir(parents=True, exist_ok=True)
todo = [r for r in rows if r[0] not in manifest]
print(f"{len(rows)} screenshots, {len(todo)} to export", flush=True)

batches, cur, names = [], [], set()
for r in todo:
    if r[4] in names or len(cur) >= 60:
        batches.append(cur); cur, names = [], set()
    cur.append(r); names.add(r[4])
if cur:
    batches.append(cur)

for n, batch in enumerate(batches, 1):
    if TMP.exists():
        shutil.rmtree(TMP)
    TMP.mkdir()
    ids = ", ".join(f'"{r[0]}/L0/001"' for r in batch)
    script = f'''tell application "Photos"
  set items_ to {{}}
  repeat with i in {{{ids}}}
    set end of items_ to media item id i
  end repeat
  export items_ to POSIX file "{TMP}" with using originals
end tell'''
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if p.returncode:
        print(f"batch {n}: export failed: {p.stderr.strip()[:200]}", flush=True)
        continue
    got = {f.name: f for f in TMP.iterdir()}
    for uuid, ts, w, h, orig in batch:
        f = got.get(orig) or next((g for k, g in got.items() if k.lower() == orig.lower()), None)
        if not f:
            print(f"  missing after export: {orig} ({uuid})", flush=True)
            continue
        when = datetime.fromtimestamp(ts, timezone.utc).astimezone()
        name = f"{when.strftime('%Y%m%d_%H%M%S')}_{uuid[:8]}{f.suffix.lower()}"
        f.rename(RAW / name)
        manifest[uuid] = {"time": when.isoformat(timespec="seconds"), "w": w, "h": h, "orig": orig, "file": name}
    man_path.write_text(json.dumps(manifest, indent=1))
    print(f"batch {n}/{len(batches)}: {len(manifest)} exported", flush=True)
if TMP.exists():
    shutil.rmtree(TMP)
print(f"done: {len(manifest)} of {len(rows)}", flush=True)
