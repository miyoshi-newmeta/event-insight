#!/usr/bin/env python3
"""GW開始時(係決めスライドを出したタイミング)に、各 #メモ-グループN へ
進め方の案内メッセージを一斉送信する。

使い方:
  cd ~/event-insight
  DISCORD_TOKEN=$(security find-generic-password -s "cred.event-insight.discord-token-main" -w) \
    SSL_CERT_FILE=$(./venv/bin/python -m certifi) ./venv/bin/python send_gw_guide.py
"""
import json
import os
import time
import urllib.request

TOKEN = os.environ["DISCORD_TOKEN"]
HD = {
    "Authorization": f"Bot {TOKEN}",
    "User-Agent": "DiscordBot (https://github.com/miyoshi/event-insight, 1.0)",
    "Content-Type": "application/json",
}

INSIGHTS_CH = 1537455974925992066
# n -> (メモch, VCch)
GROUPS = {
    1: (1537455984052670514, 1537455986892218470),
    2: (1537455990222491698, 1537455993615556618),
    3: (1537455996614610954, 1537455999508549644),
    4: (1537456002419400845, 1537456005372444753),
    5: (1537456008769573045, 1537456011722621040),
    6: (1537456014922878976, 1537456017804234762),
}

TEMPLATE = """**グループワークの進め方(このチャンネルの使い方)**

まず、グループで**3つの係**を決めてください。

⏱ **タイムキーパー**
時間を見ながら、一人に偏らず全員が話せるように回してください。

📝 **メモ係**
話に出た活用方法や「役立ちそう!」というポイントを、このチャンネルに投稿してください。全部書き取らなくて大丈夫です。係以外の方も、リンクなどお気軽にどうぞ。

🎙 **マイク調整**
お一人、ご自身のPCで <#{vc}> に参加し、マイクをオンにして、PCをテーブルの中央に置いてください。ひとこと話して、ご自身のアイコンが**緑色に点灯**すれば準備完了です。
※ ハウリング防止のため、スピーカー出力はオフ(または音量ゼロ)にしてください

3名が決まって、マイクのPCが <#{vc}> に入ったら準備OKです。
ここでの投稿と会話の記録はAIが分析し、<#{insights}> で皆さまに共有します。"""


def post(channel_id: int, content: str):
    data = json.dumps({"content": content}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        data=data, headers=HD, method="POST",
    )
    return json.load(urllib.request.urlopen(req))


if __name__ == "__main__":
    for n, (memo_ch, vc_ch) in GROUPS.items():
        post(memo_ch, TEMPLATE.format(vc=vc_ch, insights=INSIGHTS_CH))
        print(f"グループ{n}: 送信しました")
        time.sleep(1)
    print("全6グループへ送信完了")
