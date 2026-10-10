"""メイン bot (コーディネーター)。1プロセス。

役割:
  - LTコメントチャンネルの投稿を収集し、ニコニコ風オーバーレイへ WebSocket 配信
  - グループメモチャンネルの投稿を収集
  - スラッシュコマンド:
      /ei_setup  : イベント用のカテゴリ・チャンネル一式を自動作成して設定保存
      /insight   : 収集データを Claude でサマライズして投稿
      /status    : データ収集状況を表示
  - オーバーレイ配信用の Web サーバー (http://127.0.0.1:8787/)
"""
import asyncio
import json
import logging
import signal
import time
from datetime import datetime
from pathlib import Path

import discord
from aiohttp import web, WSMsgType
from discord import app_commands
from discord.ext import commands

# macOS + Python 3.14 では非ループバック接続への SO_KEEPALIVE 設定が
# EINVAL になり aiohttp が接続を落とす (aiohttp 3.14.3)。失敗を無害化する。
import aiohttp.web_protocol as _aio_wp
import aiohttp.tcp_helpers as _aio_tcp

def _safe_tcp_keepalive(transport):
    try:
        _aio_tcp.tcp_keepalive(transport)
    except OSError:
        pass

_aio_wp.tcp_keepalive = _safe_tcp_keepalive

import datastore
import eventdb
import insight as insight_mod
from config import Config, EventConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/main_bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
for noisy in ("discord", "httpx", "httpcore", "aiohttp"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

OVERLAY_DIR = Path(__file__).resolve().parent / "overlay"


class CommentHub:
    """オーバーレイ(ブラウザ)への WebSocket 配信ハブ"""

    def __init__(self):
        self.clients: set[web.WebSocketResponse] = set()

    async def broadcast(self, payload: dict):
        dead = set()
        msg = json.dumps(payload, ensure_ascii=False)
        for ws in self.clients:
            try:
                await ws.send_str(msg)
            except Exception:
                dead.add(ws)
        self.clients -= dead


hub = CommentHub()


# --- オーバーレイ Web サーバー ---

async def handle_index(request):
    return web.FileResponse(OVERLAY_DIR / "index.html")


async def handle_ws(request):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    hub.clients.add(ws)
    logger.info(f"オーバーレイ接続 (計{len(hub.clients)})")
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        hub.clients.discard(ws)
    return ws


async def handle_test_comment(request):
    """リハーサル用: curl -X POST localhost:8787/test -d '{"text":"テスト"}'"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    text = body.get("text", "テストコメントです")
    await hub.broadcast({"type": "comment", "user": "test", "text": text})
    return web.json_response({"ok": True})


async def start_overlay_server():
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_ws)
    app.router.add_post("/test", handle_test_comment)
    app.router.add_static("/static", OVERLAY_DIR)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, Config.OVERLAY_HOST, Config.OVERLAY_PORT)
    await site.start()
    logger.info(f"オーバーレイ: http://{Config.OVERLAY_HOST}:{Config.OVERLAY_PORT}/")


# --- Discord bot ---

def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)
    bot.event_config = EventConfig()

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
        try:
            synced = await bot.tree.sync()
            logger.info(f"スラッシュコマンド同期: {len(synced)}件")
        except Exception as e:
            logger.error(f"コマンド同期失敗: {e}")

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            await bot.process_commands(message)
            return

        cfg: EventConfig = bot.event_config
        comments_id = cfg.channel_id("comments")
        memo_map = cfg.memo_channel_ids()

        if comments_id and message.channel.id == comments_id:
            datastore.append_comment(message.author.display_name, message.content)
            await hub.broadcast({
                "type": "comment",
                "user": message.author.display_name,
                "text": message.content,
            })
            eventdb.fire(eventdb.post_comment(
                message.channel.id, message.channel.name,
                message.author.id, message.author.display_name, message.content,
            ))
        elif message.channel.id in memo_map:
            group = memo_map[message.channel.id]
            datastore.append_memo(group, message.author.display_name, message.content)
            eventdb.fire(eventdb.post_comment(
                message.channel.id, message.channel.name,
                message.author.id, message.author.display_name, message.content,
            ))
        elif (
            message.guild
            and isinstance(message.channel, discord.TextChannel)
            and message.channel.id != cfg.channel_id("live_transcript")
            and message.content
        ):
            # 上記以外のテキストチャンネルへの投稿も外部イベントDBへミラーする
            # (#lt-文字起こし は bot の転記で量が多いため除外)
            eventdb.fire(eventdb.post_comment(
                message.channel.id, message.channel.name,
                message.author.id, message.author.display_name, message.content,
            ))

        await bot.process_commands(message)

    # --- /ei_setup ---
    @bot.tree.command(name="ei_setup", description="イベント用のチャンネル一式を自動作成して設定を保存する")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ei_setup(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        guild = interaction.guild
        cfg: EventConfig = bot.event_config

        category = await guild.create_category(cfg.data.get("event_name", "AI Practice Forum"))

        comments = await guild.create_text_channel("lt-コメント", category=category,
                                                   topic="LT中のコメントはここへ!スクリーンに流れます")
        live = await guild.create_text_channel("lt-文字起こし", category=category,
                                               topic="登壇内容のリアルタイム文字起こし")
        insights_ch = await guild.create_text_channel("インサイト", category=category,
                                                      topic="収集データから導出したインサイトを随時展開")
        lt_vc = await guild.create_voice_channel("LT会場", category=category)

        cfg.data["guild_id"] = guild.id
        cfg.data["channels"]["comments"] = comments.id
        cfg.data["channels"]["live_transcript"] = live.id
        cfg.data["channels"]["insights"] = insights_ch.id
        cfg.data["voice"]["lt"] = lt_vc.id
        cfg.data["channels"].setdefault("memos", {})

        for g in cfg.groups:
            n = g[1:]
            memo_ch = await guild.create_text_channel(f"メモ-グループ{n}", category=category,
                                                      topic=f"グループ{n}のメモ置き場")
            vc = await guild.create_voice_channel(f"グループ{n}", category=category)
            cfg.data["channels"]["memos"][g] = memo_ch.id
            cfg.data["voice"][g] = vc.id

        cfg.save()
        await interaction.followup.send(
            f"✅ セットアップ完了!カテゴリ「{category.name}」に "
            f"テキスト{3 + len(cfg.groups)}ch・VC{1 + len(cfg.groups)}ch を作成し、"
            f"event_config.json に保存しました。\n"
            f"※ 各文字起こしbotを再起動すると自動でVCに参加します"
        )

    # --- /insight ---
    scope_choices = [app_commands.Choice(name="全体", value="all"),
                     app_commands.Choice(name="LTセッション", value="lt"),
                     app_commands.Choice(name="グループ全体", value="groups")]
    for i in range(1, 7):
        scope_choices.append(app_commands.Choice(name=f"グループ{i}", value=f"g{i}"))

    @bot.tree.command(name="insight", description="収集データをサマライズしてインサイトを生成・投稿する")
    @app_commands.describe(
        scope="対象範囲",
        audience="participant=参加者向け速報 / organizer=運営向け詳細",
        minutes="直近何分ぶんのデータを対象にするか(省略時は今日全部)",
    )
    @app_commands.choices(
        scope=scope_choices,
        audience=[app_commands.Choice(name="参加者向け速報", value="participant"),
                  app_commands.Choice(name="運営向け詳細", value="organizer")],
    )
    async def insight_cmd(interaction: discord.Interaction, scope: str = "all",
                          audience: str = "participant", minutes: int | None = None):
        await interaction.response.defer(thinking=True)
        since_ts = time.time() - minutes * 60 if minutes else None
        cfg: EventConfig = bot.event_config

        try:
            md = await asyncio.to_thread(
                insight_mod.generate_insight, scope, cfg.groups, audience, since_ts
            )
        except Exception as e:
            logger.error(f"インサイト生成失敗: {e}", exc_info=True)
            await interaction.followup.send(f"⚠️ インサイト生成に失敗しました: {e}")
            return

        window = f"直近{minutes}分" if minutes else "本日全体"
        header = f"📊 **インサイト** ({scope} / {window} / {datetime.now().strftime('%H:%M')})\n"
        chunks = insight_mod.chunk_for_discord(md)
        await interaction.followup.send(header + chunks[0])
        for chunk in chunks[1:]:
            await interaction.channel.send(chunk)

        eventdb.fire(eventdb.post_summary(
            interaction.channel.id, getattr(interaction.channel, "name", "insight"),
            f"[{scope}/{audience}/{window}]\n{md}",
        ))

    # --- /lt_marker ---
    # LT登壇の区切りを外部イベントDBの「LT会場」ストリームに注入する(Discordには表示しない)。
    # 文字起こしと同じ discordChannelId に載せることで、受け側が1本のストリーム内で
    # `[lt-marker/...]` 行を境に登壇者ごとの発話を切り出せる。
    @bot.tree.command(name="lt_marker", description="LT登壇の開始/終了の仕切りを記録用サーバーへ送る(運営用)")
    @app_commands.describe(
        action="start=登壇開始 / end=登壇終了",
        number="登壇の通し番号 (1,2,3,…)",
        label="登壇者名・タイトルなど自由記述 (start時に推奨)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="開始", value="start"),
        app_commands.Choice(name="終了", value="end"),
    ])
    async def lt_marker_cmd(interaction: discord.Interaction, action: str,
                            number: int, label: str = ""):
        cfg: EventConfig = bot.event_config
        vc_id = cfg.voice_channel_id("lt")
        if not vc_id:
            await interaction.response.send_message("⚠️ voice.lt が未設定です", ephemeral=True)
            return
        vc = bot.get_channel(vc_id)
        content = f"[lt-marker/{action}/{number}]" + (f" {label}" if label else "")
        eventdb.fire(eventdb.post_comment(
            vc_id, vc.name if vc else "LT会場",
            interaction.user.id, interaction.user.display_name, content,
        ))
        await interaction.response.send_message(f"📍 仕切りを送信しました: `{content}`", ephemeral=True)

    # --- /status ---
    @bot.tree.command(name="status", description="データ収集状況を表示する")
    async def status_cmd(interaction: discord.Interaction):
        cfg: EventConfig = bot.event_config
        c = datastore.counts(cfg.groups)
        lines = [
            f"LT文字起こし: {c['lt_transcript']}件 / コメント: {c['comments']}件",
        ]
        for g in cfg.groups:
            lines.append(f"グループ{g[1:]}: 会話{c[f'{g}_transcript']}件 / メモ{c[f'{g}_memos']}件")
        lines.append(f"オーバーレイ接続: {len(hub.clients)}画面")
        await interaction.response.send_message("📥 **収集状況**\n" + "\n".join(lines))

    @ei_setup.error
    async def ei_setup_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("チャンネル管理権限が必要です", ephemeral=True)
        else:
            logger.error(f"/ei_setup エラー: {error}", exc_info=True)

    return bot


async def main():
    if not Config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN が未設定です")
        return

    await start_overlay_server()

    bot = create_bot()

    # SIGTERM/SIGINT で Discord 接続を綺麗に閉じる
    async def shutdown():
        await eventdb.close()
        await bot.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    logger.info("Starting main bot ...")
    try:
        await bot.start(Config.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("ログイン失敗。トークンを確認してください")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
