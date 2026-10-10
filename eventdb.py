"""友人(VARET)の event-db API へのデータ送信クライアント。

Cloudflare Workers + D1 の外部DBに、コメント・メモ・文字起こし・インサイトを
リアルタイムでミラーする。ローカルの JSONL が常に正で、送信失敗はログに
残すだけで本体の動作(収集・表示)は一切止めない。

認証: Authorization: Bearer <イベントKey evk_...> (実地確認済み)
  - POST /api/comments  : チャンネル・ユーザーは自動upsert
  - POST /api/summaries : 対象チャンネルは事前登録が必要 → ensure_channel を先に呼ぶ
"""
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp

from config import Config

logger = logging.getLogger(__name__)

_session: aiohttp.ClientSession | None = None
# summaries 用: 登録済みチャンネルの記録 (プロセス内キャッシュ)
_registered_channels: set[str] = set()


def enabled() -> bool:
    return bool(Config.EVENTDB_API_KEY) and Config.EVENTDB_ENABLED


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            headers={"Authorization": f"Bearer {Config.EVENTDB_API_KEY}"},
            timeout=aiohttp.ClientTimeout(total=15),
        )
    return _session


async def close():
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


async def _post(path: str, body: dict) -> dict | None:
    """POST 1回+リトライ1回。失敗しても raise しない。"""
    url = f"{Config.EVENTDB_BASE_URL}{path}"
    for attempt in (1, 2):
        try:
            async with _get_session().post(url, json=body) as res:
                data = await res.json(content_type=None)
                if res.status in (200, 201) and data.get("success"):
                    return data
                logger.warning(f"eventdb {path} -> HTTP {res.status}: {data.get('error')}")
                return None  # 4xx はリトライしても無駄
        except Exception as e:
            if attempt == 1:
                await asyncio.sleep(1)
                continue
            logger.warning(f"eventdb {path} 送信失敗: {type(e).__name__}: {e}")
    return None


def fire(coro):
    """バックグラウンド送信 (呼び出し元を絶対にブロックしない)"""
    if enabled():
        asyncio.create_task(coro)
    else:
        coro.close()


async def post_comment(channel_id: int | str, channel_name: str,
                       user_id: int | str, username: str, content: str,
                       posted_at: str | None = None):
    """コメント・メモ・文字起こし1件を送る (チャンネル/ユーザーは自動upsert)"""
    body = {
        "channel": {"discordChannelId": str(channel_id), "name": channel_name},
        "user": {"discordUserId": str(user_id), "username": username},
        "content": content,
        "postedAt": posted_at or datetime.now(timezone.utc).isoformat(),
    }
    if await _post("/comments", body) is not None:
        _registered_channels.add(str(channel_id))


async def ensure_channel(channel_id: int | str, name: str):
    """summaries の前提となるチャンネル登録 (冪等)"""
    if str(channel_id) in _registered_channels:
        return
    body = {"discordChannelId": str(channel_id), "name": name}
    if await _post("/channels", body) is not None:
        _registered_channels.add(str(channel_id))


async def post_summary(channel_id: int | str, channel_name: str, content: str):
    """インサイト(要約)を送る。チャンネル未登録なら先に登録する"""
    await ensure_channel(channel_id, channel_name)
    await _post("/summaries", {"discordChannelId": str(channel_id), "content": content})
