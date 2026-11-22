# mini-watch

iR（ir-japan.net）の BMW/MINI 在庫から **F54 クラブマン クーパーS・支払総額200万円以下** を1日2回（8:10／19:10 JST）チェックし、スマホに通知します。

- 🆕 新着　💴 値下げ　✅ 掲載終了（売約など）　↗️ 値上げで条件外
- 現在の該当車一覧 → [STATUS.md](STATUS.md)

## 設定
1. スマホに **ntfy** アプリを入れ、推測されにくいトピック名（例 `mini-f54-xxxx`）を購読
2. リポジトリの Settings → Secrets and variables → Actions → New repository secret
   名前 `NTFY_TOPIC`、値に上のトピック名
3. Actions タブ → 「MINI在庫チェック」→ Run workflow で初回実行

条件の変更は `watch.py` 冒頭の `MAX_PRICE` / `TARGET_CODE` を編集。
