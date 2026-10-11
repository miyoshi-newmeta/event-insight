# AI Practice Forum 当日コマンド全集 (2026-10-11)

打つ場所の凡例: 💻 = Macのターミナル(~/event-insight で) / 💬 = Discordの入力欄

## 13:00 設営

💻 bot起動(コメント収集+/insight用 → LT文字起こし用):

```
./start.sh main
./start.sh lt
```

💬 収集が動いているか確認(どのチャンネルでもOK):

```
/status
```

→ 🔊LT会場 でひと言しゃべって `#lt-文字起こし` に流れればOK

## 14:10〜 LTセッション

💬 各登壇が終わった瞬間に1行ずつ(どのチャンネルでもOK):

```
/lt_marker action:終了 number:1 label:せっきー
/lt_marker action:終了 number:2 label:友部さん
/lt_marker action:終了 number:3 label:リョータ
/lt_marker action:終了 number:4 label:石島さん
/lt_marker action:終了 number:5 label:みよっしー
/lt_marker action:終了 number:6 label:田島さん
```

※ 5人目は自分の登壇。降壇した直後に打つのを忘れない。

💬 LT全体が終わった直後 (#lt-インサイト で実行。生成1〜2分):

```
/insight scope:LTセッション audience:参加者向け速報
```

## 14:55〜 グループワーク開始 (係決めスライドを出したら)

💻 各 #メモ-グループN へ進め方ガイドを一斉送信:

```
DISCORD_TOKEN=$(security find-generic-password -s "cred.event-insight.discord-token-main" -w) SSL_CERT_FILE=$(./venv/bin/python -m certifi) ./venv/bin/python send_gw_guide.py
```

💻 マイク調整のPCがVCに入り始めたら、グループbot 6台を起動:

```
./start.sh groups
```

💬 全グループの収集確認:

```
/status
```

→ 以降、各グループの会話は運営用プライベートch `#文字起こし-グループN` で覗ける

## 15:25ごろ インターバル① (R1終了のアナウンスと同時に打つ)

💬 #gw-インサイト で実行(生成1〜2分 → 記録タイムの間に完成):

```
/insight scope:グループ全体 minutes:30
```

→ 結果をスクリーンに映す or 読み上げ、30秒だけ触れてからR2説明へ

## 15:50ごろ インターバル② (R2終了のアナウンスと同時に打つ)

💬 #gw-インサイト で実行:

```
/insight scope:グループ全体 minutes:30
```

→ 「共通の壁」を30秒だけ触れてからR3説明へ

## 16:25〜 交流タイム

💻 グループbot停止(交流の雑談は録らない):

```
./start.sh stop
```

💬 本日の総まとめを生成(#lt-インサイト で実行。クロージングの「お土産」):

```
/insight scope:全体 audience:参加者向け速報
```

## 撤収後

💬 企画用レポート(**必ず #運営向け で実行** — event-dbの記録先になるため):

```
/insight scope:全体 audience:運営向け詳細
```

💬 グループ別の深掘り(同じく #運営向け で。Nは1〜6):

```
/insight scope:グループN audience:運営向け詳細
```

## 時系列ざっくり表

| 時刻 | やること | 種別 | 場所 |
|---|---|---|---|
| 13:00 | `./start.sh main` → `./start.sh lt` → `/status` | 💻💬 | ターミナル |
| 14:10〜 | 登壇終了ごとに `/lt_marker 終了 number:1〜6` | 💬 | どこでも |
| 14:55ごろ | `/insight LTセッション 参加者向け速報` | 💬 | #lt-インサイト |
| 14:55 | `send_gw_guide.py` 一斉送信 → `./start.sh groups` → `/status` | 💻💬 | ターミナル |
| 15:25ごろ | `/insight グループ全体 minutes:30` | 💬 | #gw-インサイト |
| 15:50ごろ | `/insight グループ全体 minutes:30` | 💬 | #gw-インサイト |
| 16:25 | `./start.sh stop` → `/insight 全体 参加者向け速報` | 💻💬 | #lt-インサイト |
| 撤収後 | `/insight 全体 運営向け詳細` ほか | 💬 | #運営向け |

## 朝イチの事前確認

- `./venv/bin/python verify_bots.py` で8botの健全性チェック
- 入力欄に `/lt_marker` と打って候補に出るか確認(昨夜追加したコマンドの反映待ちの可能性)
