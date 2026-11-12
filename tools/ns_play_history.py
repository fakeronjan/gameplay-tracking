#!/usr/bin/env python3
# Vendored unmodified from github.com/sibylsea-hub/ns-play-history (MIT, commit of 2026-10-07), read in full 2026-11-12.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sibyl (sibylsea-hub)
"""让你的小机（AI 伴侣）看到你的 Nintendo Switch 游玩记录（与 Nintendo Store app 里显示的是同一份数据）。

只用 Python 3 标准库，无需安装依赖。给小机用的分步命令：

  python3 ns_play_history.py auth-url          # 打印任天堂登录链接（交给用户在浏览器里打开）
  <授权链接> | python3 ns_play_history.py auth-finish
                                              # 从标准输入读用户复制的授权链接，保存登录凭证（约两年有效）
                                              # macOS: pbpaste | …   Windows: powershell Get-Clipboard | …
  python3 ns_play_history.py fetch [文件名]     # 导出全部游玩记录为 JSON（默认 play_histories.json）

人自己用的话：python3 ns_play_history.py login（交互式，一步到位）。

登录凭证存在 ~/.ns-play-history/（目录 700、文件 600），等同于账号凭证，请勿外传。
该接口没有公开文档，可能随时变化；请只用于查看你自己的账号。
"""

import base64
import getpass
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# 任天堂账号登录：使用 Nintendo Store app 的登录入口，所以确认页会显示「关联到 Nintendo Store」
CLIENT_ID = "5c38e31cd085304b"
REDIRECT_URI = f"npf{CLIENT_ID}://auth"
SCOPE = "openid user user.mii user.email user.links[].id"
ACCOUNTS = "https://accounts.nintendo.com/connect/1.0.0"

# Nintendo Store app 读取游玩记录的接口；gentry-locale 头必填（决定游戏名的语言）
API = "https://app-api.znej.nintendo.com/api/v2.0/users/me/play_histories"
LOCALE = os.environ.get("NS_LOCALE", "en-US")
USER_AGENT = "ns-play-history/1.2"

HOME = Path.home() / ".ns-play-history"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def save_secret(name: str, obj: dict) -> None:
    HOME.mkdir(mode=0o700, exist_ok=True)
    fd = os.open(HOME / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)


def load_secret(name: str):
    p = HOME / name
    return json.loads(p.read_text()) if p.exists() else None


def request(method: str, url: str, headers: dict, body: bytes = None):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


HOW_TO_COPY = (
    "登录后会出现「Select this account / 选择此人」页面：不要点按钮，在按钮上右键 → 复制链接地址；\n"
    "或按 F12 打开控制台执行：copy(document.getElementById('authorize-switch-approval-link').href)\n"
    f"复制到的应以 {REDIRECT_URI}# 开头（不是地址栏里的网址）。"
)


def auth_url() -> str:
    """生成登录链接，并把 PKCE 的 verifier/state 存起来等 auth-finish 用。"""
    verifier = b64url(os.urandom(32))
    state = b64url(os.urandom(36))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    save_secret("pending.json", {"verifier": verifier, "state": state})
    return f"{ACCOUNTS}/authorize?" + urllib.parse.urlencode({
        "state": state,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "scope": SCOPE,
        "response_type": "session_token_code",
        "session_token_code_challenge": challenge,
        "session_token_code_challenge_method": "S256",
    })


def auth_finish(link: str) -> None:
    pending = load_secret("pending.json")
    if not pending:
        sys.exit("没有待完成的登录：先运行 auth-url")
    link = link.strip()
    if not link.startswith(REDIRECT_URI + "#"):
        sys.exit(f"这不是授权链接：应以 {REDIRECT_URI}# 开头（常见错误：复制成了地址栏）")
    frag = urllib.parse.parse_qs(link.split("#", 1)[1])
    if frag.get("state", [None])[0] != pending["state"]:
        sys.exit("state 不匹配：这条链接不是最近一次 auth-url 生成的，请重新 auth-url")
    status, body = request("POST", f"{ACCOUNTS}/api/session_token", {
        "Content-Type": "application/x-www-form-urlencoded",
    }, urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "session_token_code": frag["session_token_code"][0],
        "session_token_code_verifier": pending["verifier"],
    }).encode())
    if status != 200:
        sys.exit(f"保存登录失败：HTTP {status} {body[:200]!r}（授权链接只能用一次、几分钟内有效，可重新 auth-url）")
    save_secret("session.json", {"session_token": json.loads(body)["session_token"]})
    (HOME / "pending.json").unlink(missing_ok=True)
    print(f"ok: 登录凭证已保存到 {HOME}/session.json（约两年有效）")


def access_token() -> str:
    cached = load_secret("access.json")
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]
    session = load_secret("session.json")
    if not session:
        sys.exit("还没登录：先运行 auth-url / auth-finish（或 login）")
    status, body = request("POST", f"{ACCOUNTS}/api/token", {
        "Content-Type": "application/json; charset=utf-8",
    }, json.dumps({
        "client_id": CLIENT_ID,
        "session_token": session["session_token"],
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer-session-token",
    }).encode())
    if status != 200:
        sys.exit(f"获取访问凭证失败：HTTP {status} {body[:200]!r}（登录过期的话重新登录）")
    data = json.loads(body)
    save_secret("access.json", {"token": data["access_token"], "expires_at": time.time() + data.get("expires_in", 900)})
    return data["access_token"]


def fetch(out: str = "play_histories.json") -> None:
    status, body = request("GET", API, {
        "Authorization": f"Bearer {access_token()}",
        "Accept": "application/json",
        "gentry-locale": LOCALE,
    })
    if status != 200:
        sys.exit(f"HTTP {status} {body[:300]!r}")
    Path(out).write_bytes(body)
    data = json.loads(body)
    games = data.get("playHistories", [])
    print(f"ok: {len(games)} 个游戏 → {out}"
          f"（字段：titleName, platform, totalPlayedMinutes, totalPlayedDays, firstPlayedAt, lastPlayedAt；"
          f"recentPlayHistories 为最近一周按天）")


def login() -> None:
    """给人用的交互式登录：auth-url + auth-finish 合在一起。"""
    print("1) 用浏览器打开下面的链接，登录你的任天堂账号：\n\n" + auth_url() + "\n")
    print("2) " + HOW_TO_COPY + "\n")
    auth_finish(getpass.getpass("3) 粘贴授权链接（输入不回显）："))


def main() -> None:
    cmd, rest = (sys.argv[1:] or [""])[0], sys.argv[2:]
    if cmd == "auth-url":
        print(auth_url())
        print("\n" + HOW_TO_COPY, file=sys.stderr)
    elif cmd == "auth-finish":
        auth_finish(sys.stdin.read() if not sys.stdin.isatty() else getpass.getpass("粘贴授权链接："))
    elif cmd == "fetch":
        fetch(*rest[:1])
    elif cmd == "login":
        login()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
