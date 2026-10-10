#!/bin/bash
# クレデンシャルを macOS Keychain に登録する (初回のみ)
#
# 値をシェル履歴に残さないよう、対話式で read -s する。
# Soniox / OpenAI は translation-bot の既存キーをコピーする。

set -euo pipefail

add() {
  local name="$1" value="$2"
  security add-generic-password -a "$USER" -s "cred.event-insight.$name" -A -U -w "$value"
  echo "登録: cred.event-insight.$name"
}

copy_from() {
  local src="$1" dst="$2"
  local v
  v=$(security find-generic-password -s "$src" -w 2>/dev/null) || {
    echo "スキップ: $src が見つかりません"; return
  }
  add "$dst" "$v"
}

echo "--- 既存キーのコピー (translation-bot から) ---"
copy_from cred.translation-bot.soniox-api-key soniox-api-key
copy_from cred.translation-bot.openai-api-key openai-api-key

echo ""
echo "--- 新規キーの登録 (入力は表示されません。スキップは空Enter) ---"

prompt_add() {
  local label="$1" name="$2" v
  read -r -s -p "$label: " v; echo ""
  if [ -n "$v" ]; then add "$name" "$v"; else echo "スキップ: $name"; fi
}

prompt_add "OpenRouter API キー" openrouter-api-key
prompt_add "Discord トークン (メインbot)" discord-token-main
prompt_add "Discord トークン (LT文字起こし)" discord-token-lt
for i in 1 2 3 4 5 6; do
  prompt_add "Discord トークン (グループ$i)" "discord-token-g$i"
done

echo ""
echo "完了。~/credential-manager/REGISTRY.md への追記も忘れずに。"
