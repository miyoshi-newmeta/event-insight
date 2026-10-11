# event-db 連携: summaries の content フォーマット仕様

AI Practice Forum 側 bot → event-db への送信仕様。特に `summaries.content` の1行目タグの説明。
(2026-10-10 時点 / 送信元: event-insight main_bot)

## 1. 送信エンドポイントと生ペイロード

認証はすべて `Authorization: Bearer evk_...`。

### POST /comments — 通常メッセージ(コメント・メモ・文字起こし・全テキストch投稿)

```json
{
  "channel": { "discordChannelId": "1537455967359467571", "name": "lt-コメント" },
  "user":    { "discordUserId": "123456789012345678", "username": "みよっしー" },
  "content": "投稿本文そのまま",
  "postedAt": "2026-10-11T05:12:34.567890+00:00"
}
```
チャンネル・ユーザーは受け側で自動upsertされる前提。

### POST /summaries — /insight の生成結果(これが本題)

```json
{
  "discordChannelId": "1537455974925992066",
  "content": "[groups/participant/本日全体]\n## インサイト速報\n\n### 今の盛り上がり\n..."
}
```
送信前に `POST /channels` で対象チャンネルを登録してから投げている。

## 2. summaries.content の構造

```
1行目: [<scope>/<audience>/<window>]   ← /insight コマンドの実行パラメータ(bot が機械的に付与)
2行目以降: Markdown の要約本文          ← LLM 出力(構造は揺れる)
```

生成コード(main_bot.py):

```python
window = f"直近{minutes}分" if minutes else "本日全体"
content = f"[{scope}/{audience}/{window}]\n" + 要約本文
```

AI の生成物ではなく bot が付けているタグなので、フォーマットは固定。パースして依存してよい。

## 3. 各フィールドの取りうる値

| 位置 | 値 | 意味 |
|---|---|---|
| scope | `all` | 全データ(LT文字起こし+コメント+全グループ) |
| | `lt` | LTセッションのみ(文字起こし+コメント) |
| | `groups` | 全6グループの会話+メモ(LTは含まない) ※2026-10-07追加 |
| | `g1`〜`g6` | グループ個別 |
| audience | `participant` | 参加者向け速報(短い・400〜800字) |
| | `organizer` | 運営向け詳細レポート(長い) |
| window | `直近{N}分` | minutes パラメータ指定時(N は正の整数) |
| | `本日全体` | minutes 未指定時(当日全データ) |

## 4. パース方法

### 正規表現

```
^\[(all|lt|groups|g[1-6])\/(participant|organizer)\/(直近(\d+)分|本日全体)\]\n
```

- グループ1 = scope / 2 = audience / 3 = window表記 / 4 = 分数(「本日全体」のときは未マッチ)

### パース結果の JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "InsightSummaryHeader",
  "type": "object",
  "required": ["scope", "audience", "window_minutes", "body"],
  "properties": {
    "scope": {
      "type": "string",
      "enum": ["all", "lt", "groups", "g1", "g2", "g3", "g4", "g5", "g6"],
      "description": "/insight の対象範囲"
    },
    "audience": {
      "type": "string",
      "enum": ["participant", "organizer"],
      "description": "participant=参加者向け速報 / organizer=運営向け詳細"
    },
    "window_minutes": {
      "type": ["integer", "null"],
      "minimum": 1,
      "description": "直近N分のN。本日全体(当日全データ)のときは null"
    },
    "body": {
      "type": "string",
      "description": "2行目以降のMarkdown本文(LLM出力のため構造は非保証)"
    }
  }
}
```

### 実装例(JS)

```js
const RE = /^\[(all|lt|groups|g[1-6])\/(participant|organizer)\/(直近(\d+)分|本日全体)\]\n/;
function parseSummary(content) {
  const m = content.match(RE);
  if (!m) return { scope: null, audience: null, window_minutes: null, body: content }; // 旧データ
  return {
    scope: m[1],
    audience: m[2],
    window_minutes: m[4] ? parseInt(m[4], 10) : null,
    body: content.slice(m[0].length),
  };
}
```

## 5. LT登壇者の区切り — lt-marker (2026-10-10 追加)

LT の文字起こしは **「LT会場」(VC) のチャンネル `discordChannelId: "1537455978273046568"`** に紐づく
comments として届く。登壇者ごとに切り出せるよう、運営が登壇の切り替わりで
**同じチャンネルに固定フォーマットの仕切りコメントを注入する**(bot の `/lt_marker` コマンド)。

### フォーマット

```
[lt-marker/start/<n>] <登壇者名やタイトルなど自由記述>
[lt-marker/end/<n>]
```

- `<n>` = 登壇の通し番号 (1, 2, 3, …)
- `end` は押し忘れる可能性があるので、**次の `start` も区切りとして扱う**実装を推奨

### 判定方法

LT会場チャンネルの comments のうち、content が次にマッチするものが仕切り。それ以外は文字起こし本文。

```
^\[lt-marker\/(start|end)\/(\d+)\](?:\s+(.*))?$
```

- グループ1 = start/end / 2 = 通し番号 / 3 = ラベル(任意)
- テスト行を1件送信済み: `[lt-marker/start/0] 接続テスト(仕切りフォーマットのサンプル)`(username: `lt-marker-test`)。番号 0 はテスト扱いで無視してよい

### 区切りルール (start/end どちらの運用でも切れるように)

運営の押し忘れ・省力化を考慮し、**マーカーは「区切り点」として解釈する**のが安全:

1. **区切り点** = `start` でも `end` でも、マーカーが来たらそこで区間が切り替わる
2. **区間の帰属**:
   - 区間の直前が `start/n` → その区間は登壇 n の発話
   - 区間の直後が `end/n` → その区間は登壇 n の発話 (**end だけ運用はこちら**: 「前のマーカー〜end/n」が登壇 n)
   - 両方ある場合は一致するはずだが、ズレたら `end` 側を正とする
3. `end/n` と次の `start/n+1` の間に何もなければ空区間 (登壇の合間の司会つなぎ等は直近の区切りに従って捨てるか「幕間」扱い)

**end だけ運用の例** (当日はこの省力運用の可能性が高い):

```
(文字起こし...)           ← 登壇1
[lt-marker/end/1] 山田さん「AI活用のリアル」
(文字起こし...)           ← 登壇2
[lt-marker/end/2] 佐藤さん「壁の乗り越え方」
```

この場合 `label` は「いま終わった登壇」の情報なので、区間のメタデータは end マーカーから取る。

## 6. 運営向け要約の送り先 (2026-10-10 運用決定)

`audience=organizer` の要約は **#運営向け (`discordChannelId: "1558034446798557224"`) で
/insight を実行**する運用にする。summaries の `discordChannelId` はコマンド実行チャンネルになるため、
管理者チャンネルの要約 = `discordChannelId == "1558034446798557224"` の summaries で拾える。

## 7. 注意点

- **id=1(2026-09-09 の接続テスト)はタグなし**(フォーマット確立前)。パーサは未マッチ時のフォールバックを持つこと(上の実装例のように)
- `groups` scope は 2026-10-07 追加。それ以前のデータには現れない
- 1行目は安定、本文(2行目以降)はLLM出力なので見出しレベル等は揺れる
- 将来 scope が増える可能性はある(増やす場合は事前連絡する)。未知の値を弾かず素通しにしておくのが安全
