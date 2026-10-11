import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
EVENT_CONFIG_PATH = BASE_DIR / "event_config.json"


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Discord ---
    # transcriber.py: そのプロセスが使う bot トークン（起動スクリプトがセッションごとに渡す）
    # main_bot.py:    メイン bot のトークン
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

    # transcriber.py 用: このプロセスが担当するセッション (lt / g1..g6)
    SESSION = os.getenv("EI_SESSION", "lt")

    # --- 文字起こし (Soniox) ---
    SONIOX_API_KEY = os.getenv("SONIOX_API_KEY")
    SONIOX_MODEL = os.getenv("SONIOX_MODEL", "stt-rt-v5")
    SONIOX_WEBSOCKET_URL = os.getenv(
        "SONIOX_WEBSOCKET_URL", "wss://stt-rt.soniox.com/transcribe-websocket"
    )
    SONIOX_KEEPALIVE_INTERVAL = float(os.getenv("SONIOX_KEEPALIVE_INTERVAL", "10"))
    SONIOX_FINALIZE_TOLERANCE_MS = float(os.getenv("SONIOX_FINALIZE_TOLERANCE_MS", "700"))
    SONIOX_FINALIZE_TIMEOUT = float(os.getenv("SONIOX_FINALIZE_TIMEOUT", "0.8"))
    LANGUAGE = os.getenv("EI_LANGUAGE", "ja")

    # 発話区切り: パケット途切れがこの秒数続いたら発話終了。短すぎる発話は捨てる
    SILENCE_THRESHOLD = float(os.getenv("SILENCE_THRESHOLD", "0.5"))
    MIN_DURATION = float(os.getenv("MIN_DURATION", "1.0"))

    # --- フィラー除去 (OpenAI) ---
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    POLISH_ENABLED = _flag("POLISH_ENABLED", "true")
    POLISH_MAX_TOKENS = int(os.getenv("POLISH_MAX_TOKENS", "500"))
    CONTEXT_MAX_SIZE = int(os.getenv("CONTEXT_MAX_SIZE", "10"))

    # --- サマライズ / インサイト (OpenRouter / DeepSeek) ---
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # 新しいスナップショットに変えるなら INSIGHT_MODEL=deepseek/deepseek-v4-pro-0813
    INSIGHT_MODEL = os.getenv("INSIGHT_MODEL", "deepseek/deepseek-v4-pro")
    INSIGHT_MAX_TOKENS = int(os.getenv("INSIGHT_MAX_TOKENS", "8000"))

    # --- 外部イベントDB (友人のevent-db API / Cloudflare Workers+D1) ---
    EVENTDB_API_KEY = os.getenv("EVENTDB_API_KEY")
    EVENTDB_BASE_URL = os.getenv("EVENTDB_BASE_URL", "https://event-db.varet.workers.dev/api")
    EVENTDB_ENABLED = _flag("EVENTDB_ENABLED", "true")

    # --- ニコニコ風オーバーレイ ---
    OVERLAY_HOST = os.getenv("OVERLAY_HOST", "127.0.0.1")
    OVERLAY_PORT = int(os.getenv("OVERLAY_PORT", "8787"))  # 8765はcskeep-webと衝突するため変更

    # --- データ保存 ---
    DATA_DIR = Path(os.getenv("EI_DATA_DIR", str(BASE_DIR / "data")))

    @classmethod
    def today_dir(cls) -> Path:
        d = cls.DATA_DIR / datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d


class EventConfig:
    """event_config.json の読み書き。チャンネルIDは /ei_setup が自動で書き込む。"""

    def __init__(self, path: Path = EVENT_CONFIG_PATH):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        return {
            "event_name": "AI Practice Forum",
            "groups": ["g1", "g2", "g3", "g4", "g5", "g6"],
            "guild_id": None,
            "channels": {
                "comments": None,       # LTコメント (ニコニコ表示の入力元)
                "insights": None,       # インサイト展開先
                "live_transcript": None,  # LT文字起こしのライブ投稿先 (任意)
                "memos": {},            # g1..g6 -> channel_id
            },
            "voice": {},                # lt / g1..g6 -> voice channel_id
        }

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        logger.info(f"event_config.json を保存しました: {self.path}")

    @property
    def groups(self) -> list[str]:
        return self.data.get("groups", [])

    def voice_channel_id(self, session: str) -> int | None:
        v = self.data.get("voice", {}).get(session)
        return int(v) if v else None

    def channel_id(self, key: str) -> int | None:
        v = self.data.get("channels", {}).get(key)
        return int(v) if v else None

    def live_transcript_channel_id(self, session: str) -> int | None:
        """セッションに対応する文字起こしライブ投稿先 (lt / g1..g6)"""
        if session == "lt":
            return self.channel_id("live_transcript")
        v = self.data.get("channels", {}).get("group_transcripts", {}).get(session)
        return int(v) if v else None

    def memo_channel_ids(self) -> dict[int, str]:
        """channel_id -> group名 の逆引きマップ"""
        out = {}
        for g, cid in self.data.get("channels", {}).get("memos", {}).items():
            if cid:
                out[int(cid)] = g
        return out
