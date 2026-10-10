# event-insight

イベント「AI Practice Forum」用のデータ収集・インサイト導出ツール。

**目的**: LT・グループワークで生まれるデータ(発言・コメント・メモ)を収集し、
任意のタイミングでサマライズして、参加者インサイトを導出・展開する。
今後のイベント企画と、参加者の AI 案件獲得・実務活用に活かす。

## 構成

```
【LTセッション】
  登壇者の音声 ──▶ transcriber.py (lt) ──▶ Soniox文字起こし ──▶ data/ + #lt-文字起こし
  参加者コメント ─▶ #lt-コメント ──▶ main_bot.py ──▶ data/ + ニコニコ風オーバーレイ(スクリーン投影)

【グループワーク】(参加者各自が自分の端末で自グループのVCに参加する)
  グループの会話 ─▶ transcriber.py (g1..g6) ──▶ グループ別に文字起こし ──▶ data/
  参加者のメモ ──▶ #メモ-グループN ──▶ main_bot.py ──▶ data/

【インサイト】
  /insight コマンド ──▶ DeepSeek v4 Pro (OpenRouter) がサマライズ ──▶ Discordに投稿 + data/insights/

【外部イベントDB連携】(eventdb.py)
  コメント・メモ・文字起こし ──▶ POST /api/comments ─┐
  /insight の結果            ──▶ POST /api/summaries ─┴▶ 友人のevent-db API (Cloudflare Workers + D1)
  ※ ローカルJSONLが正。送信失敗はログのみで収集は止めない。キー未登録なら送信スキップ
```

- **bot は計8アプリ**: メイン1 + 文字起こし7 (LT用1 + グループ用6)。
  1つの bot は同時に1つの VC にしか入れないため、VC の数だけトークンが必要。
- 実行環境: MacBook Pro を会場に持ち込み。オーバーレイはブラウザ全画面をプロジェクターへ。

## 事前準備

### 1. Discord アプリを8個作る

[Discord Developer Portal](https://discord.com/developers/applications) で 8 個作成
(例: `EI-Main`, `EI-LT`, `EI-G1` … `EI-G6`)。各アプリで:

1. **Bot** タブ → Token を発行(後で `register_creds.sh` に入力)
2. **Privileged Gateway Intents** → `MESSAGE CONTENT INTENT` を ON
3. **OAuth2 → URL Generator** → scope: `bot` + `applications.commands`、
   permissions: `View Channels / Send Messages / Connect / Manage Channels(メインのみ)` で招待URLを作り、サーバーに招待

### 2. クレデンシャル登録 (Keychain)

```bash
cd ~/event-insight
./register_creds.sh
```

Soniox / OpenAI キーは translation-bot から自動コピー。
OpenRouter キーと Discord トークン8本は対話入力。

### 3. チャンネル自動作成

メイン bot を起動して、サーバーの任意のチャンネルで `/ei_setup` を実行:

```bash
./start.sh main
```

カテゴリ「AI Practice Forum」に以下が自動作成され、`event_config.json` に保存される:

- テキスト: `#lt-コメント` `#lt-文字起こし` `#インサイト` `#メモ-グループ1..6`
- VC: `LT会場` `グループ1..6`

## 当日の運用

```bash
# ターミナル1: メインbot (コメント収集 + オーバーレイ + /insight)
./start.sh main

# ターミナル2: LT文字起こし (LT会場VCに自動参加)
./start.sh lt

# グループワーク開始時: g1〜g6 一括起動 (各グループのデバイスがVCに入ってから)
./start.sh groups
# 終了時
./start.sh stop
```

- **ニコニコ風表示**: ブラウザで `http://127.0.0.1:8787/` を全画面 → プロジェクターへ。
  - OBS で配信画面に重ねる場合は `http://127.0.0.1:8787/?transparent=1`
  - YouTube Liveチャット風に右サイドへ表示する場合は `http://127.0.0.1:8787/?mode=side` (発言者名も表示。`&width=400` で幅、`&font=24` で文字サイズ)
  - **クロマキー運用**(スイッチャー/キーヤーで抜く場合): `?chroma=1` でグリーンバック、
    `?chroma=blue` でブルーバック。キー色と同系のコメント色は自動で除外され、右下の接続表示も消える
  - 文字サイズ・速度: `?font=56&speed=7` (組み合わせ可: `?chroma=1&font=56`)
- **グループ集音**: 参加者それぞれが自分の端末で自グループの VC (`グループN`) に参加して話す。
  話者ごとに発言が記録される。ハウリング防止のためスピーカー出力はオフ/音量ゼロ。

### コマンド

| コマンド | 説明 |
|---|---|
| `/insight scope:全体 audience:参加者向け速報` | インサイト速報を生成して投稿(400〜800字) |
| `/insight scope:グループ3 audience:運営向け詳細 minutes:30` | 直近30分のG3の詳細レポート |
| `/status` | データ収集状況・オーバーレイ接続数 |
| `/ei_setup` | チャンネル一式の自動作成(初回のみ) |
| `!join` / `!leave` | (文字起こしbot宛) VC手動参加/退出 |

## リハーサル

```bash
# Discord不要でオーバーレイだけ確認 (2秒ごとにダミーコメントが流れる)
source venv/bin/activate && python overlay_preview.py

# 本番構成でのコメントテスト (main起動中に)
curl -X POST http://127.0.0.1:8787/test -H 'Content-Type: application/json' -d '{"text":"テスト🎉"}'

# ロジックのテスト
python -m pytest test_basic.py -q
```

## データの場所

```
data/<日付>/
  transcript_lt.jsonl      # LT文字起こし {ts, session, speaker, text, raw}
  transcript_g1..g6.jsonl  # グループ会話
  comments.jsonl           # LTコメント
  memos_g1..g6.jsonl       # グループメモ
  insights/*.md            # 生成したインサイト
```

イベント後の詳細分析は、この生データを Claude Code に読ませれば何でもできる。

## ハマりどころ (translation-bot での実績から)

- **音が取れない/corrupted stream**: Discord の DAVE E2EE が原因。`davey` パッケージ +
  transcriber.py のパッチで対応済み。`pip install davey` を忘れずに。
- **libopus**: Mac は `brew install opus` が必要 (`/opt/homebrew/lib/libopus.dylib`)。
- **初回のVC接続タイムアウト**: リトライ3回で自動回復する。ダメなら bot を再起動。
- **文字起こしが遅い**: フィラー除去 (gpt-4o-mini) 込みで実測ほぼリアルタイム。
  切りたい場合は `POLISH_ENABLED=false ./start.sh lt`。
