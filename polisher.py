"""文字起こし結果からフィラー(えー、あの等)を除去する。clean-scribe から流用。"""
import openai
import logging
from config import Config

logger = logging.getLogger(__name__)

# 実質的な内容が何も残らない発話のときにモデルが返すトークン
SKIP_TOKEN = "[SKIP]"

SYSTEM_PROMPT = """You are a transcript editor. The user message is a raw speech-to-text \
transcript of a single utterance in Japanese, spoken at an AI practice-sharing meetup event. \
Rewrite it as clean, readable text.

Remove:
- Filler words and hesitation sounds (えー, えーと, えっと, あの, あのー, その, まあ, うーん, んー)
- Stutters, false starts, and immediate self-repetitions ("あの、あの、それは" -> "それは")
- Trailing verbal tics that carry no meaning

Fix:
- Obvious speech-recognition artifacts
- Missing punctuation (add natural punctuation for readability)

Never:
- Summarize, shorten, translate, or paraphrase. Keep the speaker's own wording and tone.
- Add information, opinions, or words the speaker did not say.
- Remove a word that carries meaning. When a word could be either a filler or meaningful \
(e.g. "なんか"), keep it.
- Alter proper nouns, product names (ChatGPT, Claude, Gemini など), or technical terms.

Skip rule — output exactly {skip} ONLY when nothing at all remains after removing \
hesitation sounds and repeated backchannel grunts (e.g. "えーっと、あの、うーん", "うん、うん"). \
Anything that carries meaning must be kept no matter how short: greetings, answers ("はい", \
"そうですね"), thanks, apologies, names, and one-word replies are NOT fillers. \
When in doubt, keep the utterance.

Output ONLY the cleaned text, with no quotes, labels, or explanation."""


class Polisher:
    """フィラーと言い淀みを除去し、意味は変えない。"""

    def __init__(self):
        self.client = openai.AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
        self.model = Config.OPENAI_MODEL

    async def polish(self, text: str, context: list | None = None) -> str | None:
        """発話1つを整形する。

        整形後テキストを返す。フィラーのみだった場合は None。
        エラー時は原文をそのまま返す(発話を絶対に失わない)。
        """
        if not text or not text.strip():
            return None

        if not Config.POLISH_ENABLED:
            return text

        system_prompt = SYSTEM_PROMPT.format(skip=SKIP_TOKEN)

        if context:
            lines = [f"[{e['user']}]: {e['text']}" for e in context]
            system_prompt += (
                "\n\nRecent conversation, for context only (do not edit or repeat it):\n"
                + "\n".join(lines)
            )

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.2,
                max_tokens=Config.POLISH_MAX_TOKENS,
            )
            cleaned = response.choices[0].message.content.strip()

            if not cleaned or SKIP_TOKEN in cleaned:
                logger.debug(f"Filler-only utterance skipped: {text}")
                return None

            if cleaned != text:
                logger.debug(f"Polished: {text}  ->  {cleaned}")
            return cleaned

        except Exception as e:
            logger.error(f"Polish failed, posting raw text: {e}")
            return text

    async def close(self):
        await self.client.close()
