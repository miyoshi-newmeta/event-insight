"""イベントデータの保存・読み出し。

すべて JSONL (1行1レコード) で data/<日付>/ 以下に追記する。
  transcript_<session>.jsonl : 文字起こし {ts, session, speaker, text, raw}
  comments.jsonl             : LTコメント {ts, user, text}
  memos_<group>.jsonl        : グループメモ {ts, session, user, text}
  insights/                  : 生成したインサイトの markdown
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from config import Config

logger = logging.getLogger(__name__)


def _append(path: Path, record: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"書き込み失敗 {path}: {e}")


def _read(path: Path, since_ts: float | None = None) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since_ts is None or rec.get("ts", 0) >= since_ts:
                out.append(rec)
    return out


def now_record(**fields) -> dict:
    return {"ts": time.time(), "time": datetime.now().strftime("%H:%M:%S"), **fields}


# --- 書き込み ---

def append_transcript(session: str, speaker: str, text: str, raw: str | None = None):
    rec = now_record(session=session, speaker=speaker, text=text)
    if raw and raw != text:
        rec["raw"] = raw
    _append(Config.today_dir() / f"transcript_{session}.jsonl", rec)


def append_comment(user: str, text: str):
    _append(Config.today_dir() / "comments.jsonl", now_record(user=user, text=text))


def append_memo(group: str, user: str, text: str):
    _append(
        Config.today_dir() / f"memos_{group}.jsonl",
        now_record(session=group, user=user, text=text),
    )


def save_insight(scope: str, markdown: str) -> Path:
    d = Config.today_dir() / "insights"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{datetime.now().strftime('%H%M%S')}_{scope}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


# --- 読み出し ---

def load_transcript(session: str, since_ts: float | None = None) -> list[dict]:
    return _read(Config.today_dir() / f"transcript_{session}.jsonl", since_ts)


def load_comments(since_ts: float | None = None) -> list[dict]:
    return _read(Config.today_dir() / "comments.jsonl", since_ts)


def load_memos(group: str, since_ts: float | None = None) -> list[dict]:
    return _read(Config.today_dir() / f"memos_{group}.jsonl", since_ts)


def counts(groups: list[str]) -> dict:
    """収集状況のサマリー (/status 用)"""
    c = {
        "lt_transcript": len(load_transcript("lt")),
        "comments": len(load_comments()),
    }
    for g in groups:
        c[f"{g}_transcript"] = len(load_transcript(g))
        c[f"{g}_memos"] = len(load_memos(g))
    return c
