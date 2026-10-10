#!/bin/bash
# event-insight 起動スクリプト
#
# 使い方:
#   ./start.sh main      # メインbot (コメント収集 + オーバーレイ + /insight)
#   ./start.sh lt        # LT文字起こしbot
#   ./start.sh g1        # グループ1文字起こしbot (g1〜g6)
#   ./start.sh groups    # g1〜g6 をバックグラウンドで一括起動
#   ./start.sh stop      # バックグラウンド起動したグループbotを停止
#
# クレデンシャルは macOS Keychain (cred.event-insight.*) から取得する。
# 事前に register_creds.sh で登録しておくこと。

set -euo pipefail
cd "$(dirname "$0")"

VENV=venv/bin/activate
if [ ! -f "$VENV" ]; then
  echo "venv がありません。セットアップします..."
  python3 -m venv venv
  source "$VENV"
  pip install -r requirements.txt
else
  source "$VENV"
fi

# Python 3.14 (Homebrew) はCA証明書が未設定で SSL エラーになるため certifi を使う
export SSL_CERT_FILE=$(python -m certifi)

cred() {
  security find-generic-password -s "cred.event-insight.$1" -w 2>/dev/null || {
    echo "ERROR: Keychain に cred.event-insight.$1 がありません" >&2
    exit 1
  }
}

export SONIOX_API_KEY=$(cred soniox-api-key)
export OPENAI_API_KEY=$(cred openai-api-key)
# 外部イベントDB (友人のevent-db API)。未登録なら送信スキップで動く
if v=$(security find-generic-password -s "cred.event-insight.eventdb-api-key" -w 2>/dev/null); then
  export EVENTDB_API_KEY="$v"
else
  echo "WARN: cred.event-insight.eventdb-api-key 未登録 (外部DB送信は無効)" >&2
fi

# OpenRouter キーは /insight のみで使うため、未登録でも起動は止めない
if v=$(security find-generic-password -s "cred.event-insight.openrouter-api-key" -w 2>/dev/null); then
  export OPENROUTER_API_KEY="$v"
else
  echo "WARN: cred.event-insight.openrouter-api-key 未登録 (/insight は使えません)" >&2
fi

# オーバーレイを Tailscale/LAN の他端末からも見られるよう全IFで待ち受ける
export OVERLAY_HOST="${OVERLAY_HOST:-0.0.0.0}"

mkdir -p logs

start_bg() {
  # start_bg <名前> <トークン名> <スクリプト> [EI_SESSION]
  local name="$1" tok="$2" script="$3" session="${4:-}"
  DISCORD_TOKEN=$(cred "$tok") EI_SESSION="$session" \
    nohup python "$script" >> "logs/$name.out" 2>&1 &
  echo $! > "logs/$name.pid"
  echo "起動: $name (pid $!)"
}

case "${1:-}" in
  all)
    start_bg main discord-token-main main_bot.py
    start_bg transcriber_lt discord-token-lt transcriber.py lt
    for g in g1 g2 g3 g4 g5 g6; do
      start_bg "transcriber_$g" "discord-token-$g" transcriber.py "$g"
    done
    echo "全8bot起動。オーバーレイ: http://127.0.0.1:8787/ / 停止は ./start.sh stop"
    ;;
  main)
    export DISCORD_TOKEN=$(cred discord-token-main)
    exec python main_bot.py
    ;;
  lt)
    export DISCORD_TOKEN=$(cred discord-token-lt)
    export EI_SESSION=lt
    exec python transcriber.py
    ;;
  g[1-6])
    export DISCORD_TOKEN=$(cred "discord-token-$1")
    export EI_SESSION="$1"
    exec python transcriber.py
    ;;
  groups)
    for g in g1 g2 g3 g4 g5 g6; do
      DISCORD_TOKEN=$(cred "discord-token-$g") EI_SESSION="$g" \
        nohup python transcriber.py >> "logs/transcriber_$g.out" 2>&1 &
      echo $! > "logs/transcriber_$g.pid"
      echo "起動: $g (pid $!)"
    done
    echo "g1〜g6 をバックグラウンド起動しました。停止は ./start.sh stop"
    ;;
  stop)
    for pidfile in logs/*.pid; do
      [ -f "$pidfile" ] || continue
      pid=$(cat "$pidfile")
      kill "$pid" 2>/dev/null && echo "停止: $(basename "$pidfile" .pid) (pid $pid)" || true
      rm -f "$pidfile"
    done
    ;;
  *)
    echo "使い方: ./start.sh {all|main|lt|g1..g6|groups|stop}"
    exit 1
    ;;
esac
