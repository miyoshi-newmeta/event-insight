"""8つの bot トークンを検証する (イベント前の事前チェック用)。

  ./venv/bin/python verify_bots.py

各トークンについて:
  1. トークンが有効か (REST /users/@me)
  2. イベントサーバーに参加済みか (REST /guilds/<id>)
  3. MESSAGE CONTENT インテントが有効か (gateway 接続テスト)
"""
import asyncio
import json
import subprocess
import sys
import urllib.request

import discord

from config import EventConfig

API = "https://discord.com/api/v10"
SESSIONS = ["main", "lt", "g1", "g2", "g3", "g4", "g5", "g6"]


def token_for(session: str) -> str | None:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", f"cred.event-insight.discord-token-{session}", "-w"],
        capture_output=True, text=True,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def rest(path: str, token: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "DiscordBot (https://github.com/miyoshi/event-insight, 1.0)",
        },
    )
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


async def gateway_check(token: str) -> str:
    """message_content インテント付きで接続できるか確認する。"""
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    result = "?"

    @client.event
    async def on_ready():
        nonlocal result
        result = "OK"
        await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=30)
    except asyncio.TimeoutError:
        result = "タイムアウト"
        await client.close()
    except discord.PrivilegedIntentsRequired:
        result = "NG: MESSAGE CONTENT インテントがOFF"
    except discord.LoginFailure:
        result = "NG: トークン無効"
    except Exception as e:
        if result != "OK":
            result = f"NG: {type(e).__name__}"
    return result


async def main():
    guild_id = EventConfig().data.get("guild_id")
    print(f"サーバーID: {guild_id}\n")

    ok = True
    for session in SESSIONS:
        token = token_for(session)
        if not token:
            print(f"  {session:>4}: ❌ Keychain 未登録")
            ok = False
            continue

        status, me = rest("/users/@me", token)
        if status != 200:
            print(f"  {session:>4}: ❌ トークン無効 (HTTP {status})")
            ok = False
            continue
        name = me.get("username", "?")

        g_status, _ = rest(f"/guilds/{guild_id}", token)
        in_guild = "参加済" if g_status == 200 else f"❌ サーバー未参加 (HTTP {g_status})"

        intent = await gateway_check(token)
        mark = "✅" if (g_status == 200 and intent == "OK") else "❌"
        if mark == "❌":
            ok = False
        print(f"  {session:>4}: {mark} bot={name} / {in_guild} / インテント={intent}")

    print("\n" + ("🎉 全bot準備OK!" if ok else "⚠️ 上の❌を解消してください"))


if __name__ == "__main__":
    asyncio.run(main())
