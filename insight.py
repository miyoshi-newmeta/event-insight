"""収集データ(文字起こし・コメント・メモ)を OpenRouter (DeepSeek v4 Pro) で
サマライズし、インサイトを導出する。"""
import logging

import openai

import datastore
from config import Config

logger = logging.getLogger(__name__)

EVENT_PURPOSE = """このイベント「AI Practice Forum ~ AI活用のリアルを語る場 ~」の目的:
- 参加者(AIを実務や日常で活用している人・活用を一歩前進させたい人)のリアルな実践知を持ち寄る
- 収集データからイベント参加者のインサイトを導出し、今後のイベント企画に活かす
- 参加者が AI の案件獲得・実務活用に活かせる知見として還元する"""

SYSTEM_PROMPT = f"""あなたはイベントのインサイトアナリストです。
{EVENT_PURPOSE}

イベント中に収集された生データ(登壇の文字起こし・参加者のリアルタイムコメント・グループワークの会話とメモ)を分析し、日本語でインサイトをまとめます。

分析の観点:
- 参加者が今どんな AI 活用に関心・課題を持っているか
- 繰り返し登場するテーマ、意外な視点、盛り上がった話題
- 案件獲得・実務活用につながる具体的なヒントや事例
- 今後のイベント企画に活かせる参加者ニーズ

出力ルール:
- Markdown 形式。見出しと箇条書きで読みやすく
- データに実際にあった発言・コメントを根拠として引用する(発言者名は出してよい)
- データにないことを推測で断定しない。データが少ない場合はその旨を書く
- 全体を簡潔に。冗長な前置きや免責は不要"""

PARTICIPANT_INSTRUCTION = """参加者にそのまま Discord で共有する「インサイト速報」を書いてください。
構成: ## 今の盛り上がり / ## 注目の実践知 / ## 会場への問いかけ(1つ)
分量は全体で 400〜800 字程度。ポジティブで場が温まるトーンで。"""

ORGANIZER_INSTRUCTION = """運営向けの詳細なインサイトレポートを書いてください。
構成: ## サマリー / ## 参加者の関心・課題マップ / ## 案件獲得・実務に効く実践知 / ## 今後の企画への示唆 / ## 特筆すべき発言・コメント(引用付き)
分量に制限はありません。網羅的かつ具体的に。"""


def _format_records(records: list[dict], label: str) -> str:
    if not records:
        return f"### {label}\n(データなし)\n"
    lines = []
    for r in records:
        who = r.get("speaker") or r.get("user") or "?"
        lines.append(f"[{r.get('time', '')}] {who}: {r.get('text', '')}")
    return f"### {label} ({len(records)}件)\n" + "\n".join(lines) + "\n"


def gather_data(scope: str, groups: list[str], since_ts: float | None = None) -> str:
    """scope: 'lt' / 'g1'..'g6' / 'groups'(全グループ) / 'all'"""
    parts = []
    if scope in ("lt", "all"):
        parts.append(_format_records(datastore.load_transcript("lt", since_ts), "LT登壇の文字起こし"))
        parts.append(_format_records(datastore.load_comments(since_ts), "参加者のリアルタイムコメント"))
    if scope in ("all", "groups"):
        target_groups = groups
    else:
        target_groups = [scope] if scope in groups else []
    for g in target_groups:
        parts.append(_format_records(datastore.load_transcript(g, since_ts), f"グループ{g[1:]}の会話"))
        parts.append(_format_records(datastore.load_memos(g, since_ts), f"グループ{g[1:]}のメモ"))
    return "\n".join(parts)


def generate_insight(scope: str, groups: list[str], audience: str = "participant",
                     since_ts: float | None = None) -> str:
    """インサイトを生成して markdown を返し、ファイルにも保存する。"""
    data = gather_data(scope, groups, since_ts)
    if "(データなし)" in data and data.count("###") == data.count("(データなし)"):
        return "まだ分析できるデータが集まっていません。"

    instruction = PARTICIPANT_INSTRUCTION if audience == "participant" else ORGANIZER_INSTRUCTION

    client = openai.OpenAI(
        api_key=Config.OPENROUTER_API_KEY,
        base_url=Config.OPENROUTER_BASE_URL,
        timeout=300,
    )
    response = client.chat.completions.create(
        model=Config.INSIGHT_MODEL,
        max_tokens=Config.INSIGHT_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{instruction}\n\n以下が収集データです。\n\n{data}"},
        ],
    )
    markdown = (response.choices[0].message.content or "").strip()
    if not markdown:
        logger.warning(f"モデルが空応答を返しました (finish={response.choices[0].finish_reason})")
        return "インサイト生成に失敗しました(空応答)。もう一度実行してください。"

    path = datastore.save_insight(f"{scope}_{audience}", markdown)
    usage = response.usage
    logger.info(
        f"インサイト生成完了: {path} (model={Config.INSIGHT_MODEL} "
        f"in={usage.prompt_tokens} out={usage.completion_tokens})"
    )
    return markdown


def chunk_for_discord(text: str, limit: int = 1900) -> list[str]:
    """Discord の 2000 文字制限に合わせて行単位で分割する。"""
    chunks, current = [], ""
    for line in text.split("\n"):
        # 1行自体が長すぎる場合は強制分割
        while len(line) > limit:
            head, line = line[:limit], line[limit:]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
