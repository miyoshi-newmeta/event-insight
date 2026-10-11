"""Discord VC の音声を Soniox でリアルタイム文字起こしする。

clean-scribe (translation-bot) の実装を流用。違いは:
  - 言語ロールによるフィルタを廃止し、bot 以外の全話者を文字起こしする
  - 言語は Config.LANGUAGE (既定 ja) 固定
  - 認識コンテキストをイベント用語に変更
"""
import time
import asyncio
import collections
import json
import threading
import numpy as np
import logging
import websockets
from config import Config

from discord.ext import voice_recv

logger = logging.getLogger(__name__)

# 16kHz mono 16-bit PCM: 32 bytes per millisecond
PCM16K_BYTES_PER_MS = 32

EVENT_CONTEXT = (
    "This is a Japanese conversation at an AI practice-sharing meetup event. "
    "Topics include: AI活用, 生成AI, ChatGPT, Claude, Gemini, Copilot, プロンプト, "
    "エージェント, RAG, LLM, API, 自動化, 業務効率化, 案件, 受託, フリーランス, "
    "ライトニングトーク, グループワーク. Do not censor."
)


class AudioBuffer:
    """Discord から届く生PCMをドレインサイクル間で貯めるスレッドセーフなバッファ。"""

    def __init__(self, user):
        self.user = user
        self._chunks = []
        self._lock = threading.Lock()
        self.last_packet_time = time.time()
        self.utterance_active = False
        self.utterance_ms = 0.0

    def write(self, data):
        with self._lock:
            self._chunks.append(data)
        self.last_packet_time = time.time()

    def pop(self) -> bytes:
        with self._lock:
            if not self._chunks:
                return b""
            data = b"".join(self._chunks)
            self._chunks = []
        return data


class SonioxStream:
    """話者1人ぶんの常時接続 Soniox WebSocket セッション。

    音声は届き次第ストリームし、発話区切り(無音)は Discord パケットの途切れで
    こちら側が判定する。区切りごとに finalize を送って確定トークンを回収する。
    """

    def __init__(self, user, language, context_str, callback):
        self.user = user
        self.language = language
        self.context_str = context_str
        self.callback = callback
        self.queue = asyncio.Queue()
        self._utterance_tokens = []
        self._sent_ms = 0.0
        # [seq, target final_audio_proc_ms, discard flag, requested_at]
        self._pending_flushes = collections.deque()
        self._flush_seq = 0
        self.task = asyncio.create_task(self._run())

    def feed(self, pcm16k_bytes: bytes):
        self._sent_ms += len(pcm16k_bytes) / PCM16K_BYTES_PER_MS
        self.queue.put_nowait(pcm16k_bytes)

    def finalize_utterance(self, discard: bool = False):
        self._flush_seq += 1
        # Soniox は末尾無音を final_audio_proc_ms に数えないため許容幅を持たせる
        target_ms = max(0.0, self._sent_ms - Config.SONIOX_FINALIZE_TOLERANCE_MS)
        self._pending_flushes.append([self._flush_seq, target_ms, discard, time.time()])
        self.queue.put_nowait(json.dumps({"type": "finalize"}))
        # ゲートが満たされないまま放置されないための保険
        asyncio.create_task(self._flush_fallback(self._flush_seq))

    async def _flush_fallback(self, seq: int):
        await asyncio.sleep(Config.SONIOX_FINALIZE_TIMEOUT)
        for i, entry in enumerate(self._pending_flushes):
            if entry[0] != seq:
                continue
            discard = entry[2]
            for _ in range(i + 1):
                self._pending_flushes.popleft()
            logger.debug(
                f"Finalize gate not met within {Config.SONIOX_FINALIZE_TIMEOUT}s "
                f"for {self.user.display_name}; flushing anyway"
            )
            self._flush_utterance(discard, entry[3])
            return

    def close(self):
        self.queue.put_nowait(None)

    @property
    def dead(self) -> bool:
        return self.task.done()

    async def _run(self):
        config = {
            "api_key": Config.SONIOX_API_KEY,
            "model": Config.SONIOX_MODEL,
            "audio_format": "pcm_s16le",
            "sample_rate": 16000,
            "num_channels": 1,
            "context": self.context_str,
        }
        if self.language:
            config["language_hints"] = [self.language]

        try:
            async with websockets.connect(Config.SONIOX_WEBSOCKET_URL) as ws:
                await ws.send(json.dumps(config))
                logger.info(f"Soniox stream opened for {self.user.display_name} ({self.language})")

                sender = asyncio.create_task(self._sender(ws))
                try:
                    async for message in ws:
                        res = json.loads(message)
                        if res.get("error_code"):
                            logger.error(f"Soniox error {res['error_code']}: {res.get('error_message')}")
                            break
                        self._handle_response(res)
                        if res.get("finished"):
                            break
                finally:
                    sender.cancel()
        except Exception as e:
            logger.error(f"Soniox stream error for {self.user.display_name}: {e}", exc_info=True)
        finally:
            discard = self._pending_flushes[0][2] if self._pending_flushes else False
            self._flush_utterance(discard)
            logger.info(f"Soniox stream closed for {self.user.display_name}")

    async def _sender(self, ws):
        while True:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=Config.SONIOX_KEEPALIVE_INTERVAL)
            except asyncio.TimeoutError:
                # 無音中もセッションを維持する
                await ws.send(json.dumps({"type": "keepalive"}))
                continue

            if item is None:
                # 空テキストフレームが正しい終了合図 (空バイナリだと 408 で死ぬ)
                await ws.send("")
                return
            await ws.send(item)

    def _handle_response(self, res):
        for tok in res.get("tokens", []):
            if not tok.get("is_final"):
                continue
            text = tok.get("text", "")
            if text and not (text.startswith("<") and text.endswith(">")):
                self._utterance_tokens.append(text)

        final_ms = res.get("final_audio_proc_ms")
        if final_ms is None:
            return
        while self._pending_flushes and final_ms >= self._pending_flushes[0][1]:
            _, _, discard, requested_at = self._pending_flushes.popleft()
            self._flush_utterance(discard, requested_at)

    def _flush_utterance(self, discard: bool = False, requested_at: float = None):
        text = "".join(self._utterance_tokens).strip()
        self._utterance_tokens = []
        if not text:
            return
        if discard:
            logger.debug(f"Ignored short utterance from {self.user.display_name}: {text}")
            return
        waited = f" (stt {(time.time() - requested_at) * 1000:.0f}ms)" if requested_at else ""
        logger.info(f"Detected [{self.language}]{waited}: {text}")
        asyncio.create_task(self.callback(self.user, text, self.language))


class TranscribingSink(voice_recv.AudioSink):

    def __init__(self, callback_func):
        super().__init__()
        self.callback_func = callback_func
        self.user_buffers = {}
        self.streams = {}  # user -> SonioxStream

        self.running = True
        self.processing_task = None

        self.silence_threshold = Config.SILENCE_THRESHOLD
        self.min_duration = Config.MIN_DURATION

    def __del__(self):
        self.running = False

    def wants_opus(self) -> bool:
        return False  # PCM で受け取る

    def write(self, user, data):
        try:
            if user is None or getattr(user, "bot", False):
                return

            if user not in self.user_buffers:
                logger.debug(f"Created new AudioBuffer for user: {user.display_name}")
                self.user_buffers[user] = AudioBuffer(user)

            self.user_buffers[user].write(data.pcm)
        except Exception as e:
            logger.error(f"Error writing audio data: {e}", exc_info=True)

    def cleanup(self):
        self.running = False
        for stream in self.streams.values():
            stream.close()
        self.streams = {}
        if self.processing_task:
            self.processing_task.cancel()

    async def process_loop(self):
        """100msごとに各話者のバッファをドレインして Soniox にストリームし、
        無音で発話を区切る。"""
        logger.info("Started audio streaming loop")
        while self.running:
            now = time.time()
            for user, buffer in list(self.user_buffers.items()):
                try:
                    pcm = buffer.pop()
                    if pcm:
                        converted = self._pcm_48k_stereo_to_16k_mono(pcm)
                        if converted:
                            stream = self._get_or_create_stream(user)
                            stream.feed(converted)
                            buffer.utterance_active = True
                            buffer.utterance_ms += len(converted) / PCM16K_BYTES_PER_MS
                    elif buffer.utterance_active and now - buffer.last_packet_time > self.silence_threshold:
                        duration_s = buffer.utterance_ms / 1000.0
                        discard = duration_s < self.min_duration
                        logger.debug(
                            f"Utterance boundary for {buffer.user.display_name} "
                            f"(duration: {duration_s:.2f}s{', discarded' if discard else ''})"
                        )
                        stream = self.streams.get(user)
                        if stream is not None and not stream.dead:
                            stream.finalize_utterance(discard=discard)
                        buffer.utterance_active = False
                        buffer.utterance_ms = 0.0
                    elif (not buffer.utterance_active
                          and now - buffer.last_packet_time > Config.STREAM_IDLE_CLOSE):
                        stream = self.streams.pop(user, None)
                        if stream is not None and not stream.dead:
                            logger.info(f"Closing idle Soniox stream for {user.display_name}")
                            stream.close()
                except Exception as e:
                    logger.error(f"Error streaming audio for {user}: {e}", exc_info=True)

            await asyncio.sleep(0.1)

    def _get_or_create_stream(self, user) -> SonioxStream:
        stream = self.streams.get(user)
        if stream is None or stream.dead:
            if stream is not None:
                logger.warning(f"Soniox stream for {user.display_name} died, reconnecting...")
            stream = SonioxStream(user, Config.LANGUAGE, EVENT_CONTEXT, self.callback_func)
            self.streams[user] = stream
        return stream

    @staticmethod
    def _pcm_48k_stereo_to_16k_mono(pcm_data: bytes) -> bytes:
        """Discord PCM (48kHz stereo 16-bit) -> 16kHz mono 16-bit (Soniox 用)"""
        usable = len(pcm_data) - (len(pcm_data) % 4)
        if usable <= 0:
            return b""

        audio_np = np.frombuffer(pcm_data[:usable], dtype=np.int16)
        audio_np = audio_np.reshape(-1, 2)
        audio_mono = audio_np.mean(axis=1)
        audio_16k = audio_mono[::3]
        return audio_16k.astype(np.int16).tobytes()
