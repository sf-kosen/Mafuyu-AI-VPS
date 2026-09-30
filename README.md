# mafuyu-ai

七瀬真冬をモチーフにした Discord キャラクター bot。DeepSeek API（`deepseek-flash`）で動く。
旧ローカルLLM版は [sf-kosen/mafuyu-AI](https://github.com/sf-kosen/mafuyu-AI)。

## 動き

- サーバーで **@メンション** されたときと、**真冬の発言にリプライ** されたときに返事をする。
- チャンネルの直近のメッセージ（既定 20 件・12 時間以内）を読んで、複数人の会話として文脈を理解する。
- 真冬と話した内容から、人ごとのプロファイル（呼び方・好きなもの・話した話題など）を作って覚えておく（SQLite）。最初の会話のあとに作り、以降は3回ごとに更新。さらに直近3件のやりとりもそのまま読む。
  - `/memo` … 真冬が自分について覚えていることを見る（本人にだけ表示）
  - `/forget` … 自分についての記憶を全部消す
- 最新情報が必要なときだけ DuckDuckGo で Web 検索する（`ENABLE_WEB_SEARCH=0` で無効）。
- API 利用額をトークン数から見積もり、1日・1か月の上限（既定 $0.1 / $2）を超えたら返事をやめて 💤 リアクションだけ付ける。
  見積もりは常にピーク時の単価なので、実際の請求はこれ以下になる。DeepSeek はプリペイドなので、残高がなくなった場合も同じく 💤 になる。

## キャラの調整

`character/system_prompt.md` を編集してデプロイする。

## 構成

```
mafuyu/
  bot.py       Discord の受け口（反応条件・文脈集め・返信）
  context.py   履歴 → API メッセージへの変換（テスト対象）
  llm.py       DeepSeek 呼び出し（返事・ツールループ・メモ更新）
  memory.py    ユーザーメモ（SQLite）
  search.py    web_search ツール
  config.py    環境変数
character/     キャラ設定
deploy/        systemd ユニットとデプロイスクリプト
```

## VPS

- IPv6 のみの VPS なので、IPv4 は Cloudflare WARP（`wg-quick@wgcf`）経由で外に出る。
- bot は専用ユーザー `mafuyu` で `/opt/mafuyu/app` から動く。venv は `/opt/mafuyu/venv`、データは `/opt/mafuyu/data`。
- 秘密情報は `/opt/mafuyu/.env`（`.env.example` 参照、パーミッション 600）。

```bash
deploy/deploy.sh                                   # 反映して再起動（接続先は deploy/.deploy.env）
ssh ... 'sudo journalctl -u mafuyu -f'             # ログ
ssh ... 'sudo systemctl restart mafuyu'            # 再起動
```

## テスト

```bash
python -m unittest discover -s tests -t .
```
