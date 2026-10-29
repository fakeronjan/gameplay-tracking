"""Rebuild and publish after new Switch or PlayStation screenshots are copied into the archives.

Run by hand after a copy (a few times a year). It does nothing unless the archives changed since
the last successful run and nothing has been copied in for QUIET seconds; --force skips both
checks. It rebuilds the Switch play history (build_frozen -> build_games -> fetch_images),
pushes gameplay-tracking, rebuilds the galleries and trophy moments (build_gallery), and pushes
gameplay-screenshots. A new Switch game or PlayStation folder needs a config entry and fails
loudly; the details are in local/sync.log.

    .venv/bin/python tools/sync_screenshots.py [--force]
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
SHOTS = HERE.parent / "gameplay-screenshots"
ARCHIVES = [Path.home() / "Documents/Archive/Nintendo/Nintendo Switch Screenshots",
            Path.home() / "Documents/Archive/Sony PlayStation Screenshots"]
STATE = HERE / "local" / "sync_state.json"
LOG = HERE / "local" / "sync.log"
QUIET = 600
PY = sys.executable
BOT = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def log(msg):
    with LOG.open("a") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def notify(title, msg):
    subprocess.run(["osascript", "-e", f"display notification {json.dumps(msg)} with title {json.dumps(title)}"])


def run(cmd, cwd=HERE):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    log(f"$ {' '.join(map(str, cmd))}\n{p.stdout}{p.stderr}".rstrip())
    if p.returncode:
        raise RuntimeError(f"{Path(str(cmd[1] if cmd[0] == PY else cmd[0])).name} failed: "
                           f"{(p.stderr or p.stdout).strip().splitlines()[-1] if (p.stderr or p.stdout).strip() else p.returncode}")
    return p.stdout


def fingerprint():
    """Image count and newest change time across both archives"""
    count, newest = 0, 0.0
    for d in ARCHIVES:
        for f in d.rglob("*"):
            if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                count += 1
                newest = max(newest, f.stat().st_mtime)
    return count, newest


def publish(repo, paths, message):
    """Commit and push generated files. If the daily workflow pushed first, start over from
    its commit and rebuild, since every file here is generated."""
    run(["git", "add", "-A", *paths], repo)
    if not subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=repo).returncode:
        return False
    run(["git", "commit", "-qm", f"{message}\n\n{BOT}"], repo)
    run(["git", "push", "-q"], repo)
    return True


def clean_and_current(repo):
    if run(["git", "status", "--porcelain"], repo).strip():
        raise RuntimeError(f"{repo.name} has uncommitted changes; left it alone")
    run(["git", "pull", "-q", "--rebase"], repo)


def build_and_publish():
    for attempt in range(3):
        try:
            for repo in (HERE, SHOTS):
                clean_and_current(repo)
            run([PY, "build_frozen.py"])
            run([PY, "build_games.py"])
            run([PY, "fetch_images.py"])
            for f in (HERE / "docs" / "data").glob("*.json"):
                json.loads(f.read_text())  # never publish a data file that doesn't parse
            data = publish(HERE, ["docs/data", "docs/img"], "Add new Switch screenshots to play history")
            out = run([PY, "build_gallery.py"])
            shots = publish(SHOTS, ["docs"], "Add new screenshots and trophy moments")
            return data, shots, out
        except RuntimeError as e:
            if "push" not in str(e) or attempt == 2:
                raise
            for repo in (HERE, SHOTS):  # someone pushed first: drop our commit, redo from theirs
                run(["git", "fetch", "-q"], repo)
                run(["git", "reset", "-q", "--hard", "@{u}"], repo)


def main():
    force = "--force" in sys.argv
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    count, newest = fingerprint()
    if not force and [count, newest] == state.get("done"):
        return
    if not force and time.time() - newest < QUIET:
        log(f"{count} images, still copying (last change {datetime.fromtimestamp(newest):%H:%M}); waiting")
        return
    log(f"{count} images (was {(state.get('done') or ['?'])[0]}); rebuilding")
    try:
        data, shots, out = build_and_publish()
    except Exception as e:
        log(f"FAILED: {e}")
        notify("Gameplay Stats", f"Screenshot update failed: {e}. Log: local/sync.log")
        raise SystemExit(1)
    STATE.write_text(json.dumps({"done": [count, newest], "at": datetime.now().isoformat(timespec="seconds")}))
    summary = " ".join(l for l in out.splitlines() if l.startswith("gallery:"))
    log(f"done: data {'pushed' if data else 'unchanged'}, screenshots {'pushed' if shots else 'unchanged'}")
    notify("Gameplay Stats", f"New screenshots published. {summary}" if data or shots else "Screenshots checked; nothing new to publish")


if __name__ == "__main__":
    main()
