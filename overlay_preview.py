"""オーバーレイの単体プレビュー (Discord 不要のリハーサル用)。

  python overlay_preview.py
で Web サーバーだけ起動し、2秒ごとにダミーコメントを流す。
本番と同じ http://127.0.0.1:8765/ で確認できる。
"""
import asyncio
import itertools
import logging

import main_bot
from config import Config

logging.basicConfig(level=logging.INFO)

SAMPLES = [
    "わかる〜!",
    "それ知りたかった",
    "Claude最高",
    "888888",
    "うちの会社でもやってみたい",
    "プロンプトどうしてるんだろう",
    "なるほど、RAGか…",
    "案件につながりそう!",
    "スライドあとで共有してほしい",
    "🔥🔥🔥",
]


async def main():
    await main_bot.start_overlay_server()
    print(f"→ ブラウザで http://{Config.OVERLAY_HOST}:{Config.OVERLAY_PORT}/ を開いてください")
    for text in itertools.cycle(SAMPLES):
        await asyncio.sleep(2)
        await main_bot.hub.broadcast({"type": "comment", "user": "preview", "text": text})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
