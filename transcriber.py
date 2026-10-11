"""音声文字起こし bot (セッションごとに1プロセス起動する)。

環境変数:
  DISCORD_TOKEN : この bot のトークン
  EI_SESSION    : 担当セッション (lt / g1..g6)

起動すると event_config.json の voice[EI_SESSION] の VC に自動参加して
文字起こしを開始する。VC 未設定時は !join コマンドで手動参加。
文字起こしは data/<日付>/transcript_<session>.jsonl に追記され、
lt セッションで channels.live_transcript が設定されていればそこにも投稿する。
"""
import discord
from discord.ext import commands, voice_recv
import asyncio
import collections
import os
import ctypes.util
import logging
import signal
import time

from config import Config, EventConfig
from polisher import Polisher
from audio_processing import TranscribingSink
import datastore
import eventdb

SESSION = Config.SESSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(f"logs/transcriber_{SESSION}.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
for noisy in ("discord", "discord.ext.voice_recv", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# --- libopus 読み込み (Mac) ---
if not discord.opus.is_loaded():
    opus_path = ctypes.util.find_library("opus")
    if not opus_path and os.path.exists("/opt/homebrew/lib/libopus.dylib"):
        opus_path = "/opt/homebrew/lib/libopus.dylib"
    if opus_path:
        try:
            discord.opus.load_opus(opus_path)
            logger.info(f"Loaded libopus from {opus_path}")
        except Exception as e:
            logger.error(f"Failed to load libopus: {e}")

# --- Monkey Patch: DAVE E2EE 復号 + Opus 安全化 ---
# discord-ext-voice-recv は DAVE E2EE 未対応 (0.5.3a 時点)。トランスポート層
# (NaCl) は復号するが DAVE 暗号のまま Opus に渡して "corrupted stream" になる。
# davey.DaveSession で Opus デコード前に DAVE フレームを復号する。
try:
    import davey
    _has_davey = True
except ImportError:
    _has_davey = False

from discord.ext.voice_recv.opus import PacketDecoder as _PacketDecoder

_original_decode_packet = _PacketDecoder._decode_packet


def _dave_decode_packet(self, packet):
    assert self._decoder is not None

    if packet and _has_davey:
        vc = self.sink.voice_client
        dave_session = getattr(vc._connection, "dave_session", None) if vc else None

        if dave_session and dave_session.ready:
            user_id = vc._get_id_from_ssrc(self.ssrc) if vc else None
            if user_id and packet.decrypted_data:
                try:
                    decrypted = dave_session.decrypt(user_id, davey.MediaType.audio, packet.decrypted_data)
                    if decrypted is not None:
                        packet.decrypted_data = decrypted
                except Exception as e:
                    logger.debug(f"DAVE decrypt failed for user {user_id}: {e}")

    try:
        return _original_decode_packet(self, packet)
    except Exception as e:
        if "corrupted stream" in str(e):
            logger.debug(f"Opus decode error (returning silence): {e}")
        else:
            logger.warning(f"Opus decode error (returning silence): {e}")
        return packet, b"\x00" * 3840


_PacketDecoder._decode_packet = _dave_decode_packet


def create_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=commands.when_mentioned_or("!"), intents=intents)
    bot.active_sink = None
    bot.event_config = EventConfig()
    bot.polisher = Polisher()
    # 直近の会話 (polish のコンテキスト用)
    bot.context = collections.deque(maxlen=Config.CONTEXT_MAX_SIZE)

    async def start_transcribing(vc, live_channel=None):
        async def callback(user, text, language):
            if not text:
                return
            raw = text
            t0 = time.perf_counter()
            cleaned = await bot.polisher.polish(text, context=list(bot.context))
            polish_ms = (time.perf_counter() - t0) * 1000

            if cleaned is None:
                logger.info(f"Skipped (filler only) {user.display_name}: {text}")
                return

            bot.context.append({"user": user.display_name, "text": cleaned})
            datastore.append_transcript(SESSION, user.display_name, cleaned, raw=raw)
            logger.info(f"[{SESSION}] {user.display_name} [polish {polish_ms:.0f}ms]: {cleaned}")

            # 外部イベントDBへもミラー (VCのチャンネルIDに紐づくコメントとして)
            eventdb.fire(eventdb.post_comment(
                vc.channel.id, vc.channel.name, user.id, user.display_name, cleaned,
            ))

            if live_channel:
                # グループはテーブル中央のPC1台で全員の声を拾うため、発話者名ではなくグループ名義で流す
                speaker = user.display_name if SESSION == "lt" else f"グループ{SESSION[1:]}"
                try:
                    await live_channel.send(f"**{speaker}**: {cleaned}")
                except Exception as e:
                    logger.error(f"ライブ投稿失敗: {e}")

        sink = TranscribingSink(callback)
        vc.listen(sink)
        bot.loop.create_task(sink.process_loop())
        bot.active_sink = sink
        logger.info(f"[{SESSION}] {vc.channel.name} で文字起こし開始")

    async def connect_vc(channel) -> voice_recv.VoiceRecvClient | None:
        for attempt in range(3):
            try:
                return await channel.connect(cls=voice_recv.VoiceRecvClient, timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning(f"VC接続タイムアウト。リトライ ({attempt + 1}/3)...")
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"VC接続失敗: {e}", exc_info=True)
                return None
        return None

    @bot.event
    async def on_ready():
        logger.info(f"Logged in as {bot.user} (ID: {bot.user.id}) session={SESSION}")

        # 設定済みVCに自動参加
        vc_id = bot.event_config.voice_channel_id(SESSION)
        if not vc_id:
            logger.warning(f"voice.{SESSION} が未設定。!join で手動参加してください")
            return
        if bot.voice_clients:
            return  # 再接続時など、既に入っている

        channel = bot.get_channel(vc_id)
        if channel is None:
            logger.error(f"VCが見つからない: {vc_id}")
            return

        # lt は #lt-文字起こし、g1..g6 は運営用プライベートch #文字起こし-グループN へライブ投稿
        live_channel = None
        live_id = bot.event_config.live_transcript_channel_id(SESSION)
        if live_id:
            live_channel = bot.get_channel(live_id)

        vc = await connect_vc(channel)
        if vc:
            await start_transcribing(vc, live_channel)

    @bot.command()
    async def join(ctx):
        """コマンド送信者のいるVCに参加して文字起こし開始"""
        if not ctx.author.voice:
            await ctx.send("VCに入ってから実行してね")
            return
        if ctx.voice_client and ctx.voice_client.is_connected():
            await ctx.voice_client.move_to(ctx.author.voice.channel)
            vc = ctx.voice_client
        else:
            vc = await connect_vc(ctx.author.voice.channel)
        if vc is None:
            await ctx.send("VC接続に失敗しました")
            return
        if bot.active_sink is None:
            live_id = bot.event_config.live_transcript_channel_id(SESSION)
            live_channel = bot.get_channel(live_id) if live_id else None
            await start_transcribing(vc, live_channel)
        await ctx.send(f"[{SESSION}] {vc.channel.name} で文字起こし中")

    @bot.command()
    async def leave(ctx):
        """文字起こしを止めてVCから退出"""
        if ctx.voice_client:
            if bot.active_sink:
                bot.active_sink.cleanup()
                bot.active_sink = None
            await ctx.voice_client.disconnect()
            await ctx.send("退出しました")
        else:
            await ctx.send("VCに入っていません")

    return bot


async def main():
    if not Config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN が未設定です")
        return
    if not Config.SONIOX_API_KEY:
        logger.error("SONIOX_API_KEY が未設定です")
        return

    bot = create_bot()

    # SIGTERM/SIGINT で VC 退出を送ってから終了する (即killだとDiscordに幽霊が残る)
    async def shutdown():
        logger.info("シャットダウン: VCから退出します")
        if bot.active_sink:
            bot.active_sink.cleanup()
            bot.active_sink = None
        await eventdb.close()
        await bot.close()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    logger.info(f"Starting transcriber for session={SESSION} ...")
    try:
        await bot.start(Config.DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("ログイン失敗。トークンを確認してください")
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
