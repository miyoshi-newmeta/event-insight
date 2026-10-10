"""Discord REST API でイベント用チャンネル一式を作成し、event_config.json に保存する。

  ./venv/bin/python setup_channels.py <GUILD_ID>

トークンは Keychain の cred.event-insight.discord-token-main から取得。
既に同名チャンネルがあれば作成せず、そのIDを設定に取り込む(再実行しても安全)。
"""
import json
import subprocess
import sys
import time
import urllib.request

from config import EventConfig

API = "https://discord.com/api/v10"

CATEGORY_LT = "LTセッション"
CATEGORY_GW = "グループワーク"

# type: 0=text, 2=voice, 4=category
PLAN_LT_TEXT = [
    ("lt-コメント", "comments", "LT中のコメントはここへ!スクリーンに流れます"),
    ("lt-文字起こし", "live_transcript", "登壇内容のリアルタイム文字起こし"),
    ("インサイト", "insights", "収集データから導出したインサイトを随時展開"),
]


def _token() -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", "cred.event-insight.discord-token-main", "-w"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit("ERROR: Keychain に cred.event-insight.discord-token-main がありません")
    return r.stdout.strip()


def _req(method: str, path: str, token: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            # Discord は User-Agent 必須 (無いと Cloudflare 1010 で 403)
            "User-Agent": "DiscordBot (https://github.com/miyoshi/event-insight, 1.0)",
        },
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limit
                retry = float(json.loads(e.read()).get("retry_after", 1.5))
                time.sleep(retry + 0.2)
                continue
            detail = e.read().decode(errors="replace")
            sys.exit(f"ERROR: {method} {path} -> {e.code}: {detail}")
    sys.exit("ERROR: rate limit が解除されませんでした")


def main():
    if len(sys.argv) != 2:
        sys.exit("使い方: python setup_channels.py <GUILD_ID>")
    guild_id = sys.argv[1]
    token = _token()

    me = _req("GET", "/users/@me", token)
    print(f"bot: {me['username']} (id {me['id']})")

    existing = _req("GET", f"/guilds/{guild_id}/channels", token)
    by_name = {}
    for ch in existing:
        by_name.setdefault((ch["type"], ch["name"]), ch)

    def ensure(name: str, ch_type: int, parent_id: str | None = None, topic: str | None = None) -> str:
        key = (ch_type, name)
        if key in by_name:
            print(f"  既存を利用: {name} ({by_name[key]['id']})")
            return by_name[key]["id"]
        body = {"name": name, "type": ch_type}
        if parent_id:
            body["parent_id"] = parent_id
        if topic:
            body["topic"] = topic
        ch = _req("POST", f"/guilds/{guild_id}/channels", token, body)
        by_name[key] = ch
        kind = {0: "#", 2: "🔊", 4: "📁"}[ch_type]
        print(f"  作成: {kind}{name} ({ch['id']})")
        time.sleep(0.3)  # rate limit にやさしく
        return ch["id"]

    cfg = EventConfig()
    cfg.data["guild_id"] = int(guild_id)
    cfg.data["channels"].setdefault("memos", {})

    print(f"カテゴリ「{CATEGORY_LT}」...")
    cat_lt = ensure(CATEGORY_LT, 4)
    for name, key, topic in PLAN_LT_TEXT:
        cfg.data["channels"][key] = int(ensure(name, 0, cat_lt, topic))
    cfg.data["voice"]["lt"] = int(ensure("LT会場", 2, cat_lt))

    print(f"カテゴリ「{CATEGORY_GW}」...")
    cat_gw = ensure(CATEGORY_GW, 4)
    for g in cfg.groups:
        n = g[1:]
        cfg.data["channels"]["memos"][g] = int(
            ensure(f"メモ-グループ{n}", 0, cat_gw, f"グループ{n}のメモ置き場")
        )
        cfg.data["voice"][g] = int(ensure(f"グループ{n}", 2, cat_gw))

    cfg.save()
    print("\n✅ 完了。event_config.json に保存しました:")
    print(json.dumps(cfg.data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
