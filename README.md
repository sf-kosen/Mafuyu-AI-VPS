# Mafuyu-AI-VPS

七瀬真冬をモチーフにした Discord キャラクター bot。DeepSeek API で動き、VPS 上で常駐する。

旧ローカルLLM版（Ollama / Qwen）は [sf-kosen/mafuyu-AI](https://github.com/sf-kosen/mafuyu-AI)。
小さいローカルモデルを補うためのルーター・ReAct・Codex 連携などはすべて外し、API のモデル1本で動く小さな構成に作り直した。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-4D6BFE.svg)](https://api-docs.deepseek.com/)
[![Discord](https://img.shields.io/badge/Discord-Bot-5865F2.svg)](https://discord.com/)

## できること

- **会話**：サーバーで `@メンション` されたとき、または真冬の発言に**リプライ**されたときに返事をする。
- **複数人の文脈**：チャンネルの直近のメッセージ（既定 20 件・12 時間以内）を読み、誰が何を話しているかを理解したうえで、話しかけてきた人に返事をする。
- **人ごとの記憶**：真冬と話した内容から、その人のプロファイル（呼び方の希望・好きなもの・話した話題など）を作って覚える。直近 3 件のやりとりもそのまま読むので、「さっきの続き」が通じる。
  - `/memo` … 真冬が自分について覚えていることを見る（本人にだけ表示）
  - `/forget` … 自分についての記憶を全部消す
- **調べもの**：必要なときだけ道具を使う。
  - 天気は気象庁の予報（`get_weather`、市区町村名から地域を特定）
  - ニュース・事実確認・おすすめや比較は Web 検索（`web_search`。VPS 内の SearXNG で Google・Bing・DuckDuckGo をまとめて検索し、使えないときは Serper → DuckDuckGo。上位5サイトを読んで質問に関係する段落だけを渡すので、ページを丸ごと読ませるより安い。比較のときは言い回しを変えた検索も足す）
  - 貼られた URL や検索結果のページは本文を読む（`read_url`）
- **使いすぎ防止**：API 利用額を見積もり、1日・1か月の上限を超えたら返事をやめて 💤 リアクションだけ付ける。
- **プロンプトインジェクション対策**：なりすまし・設定の聞き出し・記憶の汚染などに対する多層の対策（[後述](#セキュリティ)）。

## 技術概要

### 全体の流れ

```text
Discord ──(メンション/リプライ)──▶ bot.py
                                     │ 反応するか判定（サーバー制限・連投制限・予算）
                                     │ チャンネル履歴・プロファイル・過去のやりとりを集める
                                     ▼
                                 context.py ── 無害化（safety.py）
                                     │ API に渡すメッセージを組み立てる
                                     ▼
                                   llm.py ──▶ DeepSeek API（deepseek-flash, 思考モード）
                                     │  ▲        │ 必要なら道具を呼ぶ（最大3回）
                                     │  └────────┘ tools.py → 天気・検索・URL読み取り
                                     ▼
                           後処理（整形・設定漏れ検知）──▶ Discord に返信
                                     │
                                     ▼ バックグラウンド
                           memory.py にやりとりを記録 → 数回ごとにプロファイル更新
```

### モデル

| 項目 | 内容 |
| --- | --- |
| モデル | `deepseek-flash`（DeepSeek-V4.1-Flash）。OpenAI 互換 API を `openai` SDK で呼ぶ |
| 思考モード | 本番では有効（`THINKING=1`）。日本語のノリや会話の流れが自然になる代わりに、返事に 3〜4 秒かかる |
| プロファイル更新 | 別の呼び出しで、思考モードなし・低温度で生成する |
| キャッシュ | キャラ設定をプロンプトの先頭に固定し、DeepSeek のプレフィックスキャッシュが効くようにしている |

比較した結果（同じ会話6件、ピーク時単価）：

| 設定 | 1回あたり | 返事の速さ | 所感 |
| --- | --- | --- | --- |
| flash・思考なし | 約 $0.0002 | 1.6 秒 | 安いが、たまに会話の書式が崩れる |
| **flash・思考あり（採用）** | 約 $0.0006 | 3.5 秒 | いちばん自然 |
| pro・思考なし | 約 $0.0008 | 6.7 秒 | ジョークに強いが遅く、たまにずれる |

### プロンプトの組み立て

API に渡すメッセージは次の順に並ぶ。

1. **system**：キャラ設定（`character/system_prompt.md`、固定）→ 現在時刻 → 話しかけてきた人のプロファイル → その人との過去のやりとり
2. **user / assistant**：チャンネルの直近の発言。真冬の発言は assistant、ほかの人の発言は `[名前] 内容` の形で user にまとめる
3. 最後の user の末尾に、`▼ いまあなたに話しかけている発言（これに返事する）` という見出しを付けて、返事の対象を分けて置く

返事の対象を見出しで分けているのは、複数人が話しているときに、別の人との話の続きを返してしまうのを防ぐため。リプライの場合は「誰のどの発言への返信か」も必ず付ける。

### 記憶（プロファイル）

- SQLite（`data/mafuyu.sqlite3`）に、ユーザーごとのプロファイルと直近 30 件のやりとりを保存する。
- 最初の会話のあとにプロファイルを作り、以降は 3 回ごとに更新する。
- 項目は「呼び方の希望 / 好きなもの・興味 / やっていること・所属 / 最近の出来事 / 真冬と話した話題 / 話し方・ノリ / その他」。
- 作るのは真冬に話しかけた内容からだけ。チャンネルで他の人と話しているだけの人は記録しない。
- パスワード・本名・住所など、個人を特定できる情報は書かないよう指示している。

### 料金の管理

- 返事のたびに API が返すトークン数（キャッシュのヒット・ミス、出力）から料金を見積もり、日ごとに SQLite に記録する。
- 見積もりは常に**ピーク時の単価**（高いほう）で計算するので、実際の請求は記録額以下になる。
- 1日・1か月の上限（既定 $0.1 / $2、日本時間で切り替わり）を超えたら、API を呼ばずに 💤 リアクションだけ付ける。
- DeepSeek はプリペイドなので、残高がなくなった場合（HTTP 402）も同じく 💤 になり、チャージ額以上は請求されない。
- 目安：flash・思考ありで 1 回 約 $0.0006、月 $2 で約 3,400 回返事できる。

### セキュリティ

Discord の発言、プロファイル、過去のやりとり、検索結果はすべて**信頼できないデータ**として扱う。

| 対策 | 内容 |
| --- | --- |
| 区切りの偽造防止 | 発言中の `▼` や `[名前]` を無害な文字に置き換え、2行目以降を字下げする。名前の記号も除去する。別人の発言や返事の対象の見出しを偽造できない |
| データの引用化 | プロファイル・過去のやりとり・検索結果は `> ` 付きの引用ブロックとして渡し、見出しや指示に見えないようにする |
| 他人の記憶を渡さない | プロファイルは話しかけてきた本人の分だけを渡す。聞き出そうとしても、そもそも手元にない |
| 記憶の汚染防止 | プロファイルを保存する前に、「今後は」「ルール」「語尾」「開発者」などを含む命令っぽい行を取り除く |
| 設定漏れの検知 | 返事にキャラ設定の文がそのまま含まれていたら、送る前に差し替えてログに残す |
| キャラ設定での指示 | 従うのは設定文だけ。「管理者です」「システム：」などの発言もふつうの人として扱う |
| 通知の暴発防止 | `AllowedMentions.none()` で、返事から `@everyone` やユーザーへの通知が飛ばない |
| URL 読み取りの制限 | `read_url` と `web_search` のページ読み込みは http(s) だけ、リダイレクト先も含めて毎回名前解決し、内部・ループバック・リンクローカルなどのアドレスには接続しない（SSRF 対策）。サイズと時間にも上限 |
| 中国語の混入対策 | DeepSeek がたまに中国語の単語（模型＝モデル など）を混ぜるので、簡体字や中国語の単語を見つけたら一度だけ言い直させる |
| 乱用対策 | 反応するサーバーを限定（`ALLOWED_GUILD_IDS`）、同じ人の連投は 3 秒間無視、予算の上限 |

LLM への注入対策は確率的なもので、完全ではない。ただし bot が持つ道具は読み取り専用（検索・公開ページの閲覧・天気）だけで、通知と予算は仕組みで止めているので、突破されても「変なことを言う」程度に収まる設計にしている。

## ディレクトリ構成

```text
mafuyu/
  __main__.py  起動（python -m mafuyu）
  bot.py       Discord の受け口（反応条件・文脈集め・返信・スラッシュコマンド）
  context.py   履歴 → API メッセージの組み立て、返事の整形
  llm.py       DeepSeek 呼び出し（返事・ツールループ・プロファイル更新）
  memory.py    プロファイルとやりとりの保存（SQLite）
  budget.py    利用額の見積もりと上限
  safety.py    プロンプトインジェクション対策
  tools.py     モデルが使える道具の一覧
  research.py  web_search（複数検索・上位ページの読み込み・関係する段落の抜き出し）
  search.py    検索エンジン（SearXNG → Serper → DuckDuckGo の順に、設定があるものを使う）
  web.py       read_url（本文抽出と SSRF 対策）
  weather.py   get_weather（気象庁の予報 JSON）
  config.py    環境変数の読み込み
character/
  system_prompt.md  キャラ設定
deploy/
  deploy.sh           VPS への反映スクリプト
  mafuyu.service      systemd ユニット
  .deploy.env.example 接続先のひな形
  searxng/           SearXNG の導入スクリプト・設定・systemd ユニット
  network/           WARP が切れないようにする設定と見張りタイマー
tests/         unittest
```

## セットアップ

### 1. Discord bot を用意する

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリを作り、「Bot」タブでトークンを発行する。
2. 同じ画面で **MESSAGE CONTENT INTENT** をオンにする。
3. 「OAuth2 → URL Generator」で scopes に `bot` と `applications.commands`、権限に View Channels / Send Messages / Send Messages in Threads / Read Message History / Add Reactions を選び、できた URL からサーバーに招待する。

### 2. DeepSeek の API キーを用意する

[DeepSeek Platform](https://platform.deepseek.com) で API キーを発行し、残高をチャージする。

### 3. VPS を準備する（Ubuntu 22.04）

```bash
sudo apt install -y python3-venv
sudo useradd --system --create-home --home-dir /opt/mafuyu --shell /usr/sbin/nologin mafuyu
sudo -u mafuyu python3 -m venv /opt/mafuyu/venv
```

`.env.example` を元に `/opt/mafuyu/.env` を作り、`mafuyu` ユーザーだけが読めるようにする（`chmod 600`）。

> **IPv6 しかない VPS の場合**：Discord と DeepSeek は IPv4 でしかつながらない。
> Cloudflare WARP を [wgcf](https://github.com/ViRb3/wgcf) で登録し、WireGuard で **IPv4 だけ** WARP に流す
> （`AllowedIPs = 0.0.0.0/0`、`Endpoint` は WARP の IPv6 アドレス）。IPv6 と SSH は直接つながったままになる。
> 設定は `/etc/wireguard/wgcf.conf`、`systemctl enable --now wg-quick@wgcf` で常時有効にする。
>
> `systemd-networkd` は再起動のたびに自分が作っていないルーティングルールを消すため、自動アップデートで
> WARP のルールが消えて bot が止まることがある。`deploy.sh` が `deploy/network/install.sh` を実行し、
> networkd がルールを消さない設定と、2 分ごとに IPv4 を確認して切れていれば WARP と bot を再起動する
> `mafuyu-netwatch.timer` を入れる。ログは `journalctl -u mafuyu-netwatch` で見られる。

### 4. 検索エンジン SearXNG を入れる（任意・おすすめ）

VPS の中だけで使う SearXNG を立てると、Google・Bing・DuckDuckGo の結果を無料・回数無制限でまとめて検索できる。

```bash
# リポジトリを VPS に置いた状態で（deploy.sh 後なら /opt/mafuyu/app/deploy/searxng）
bash deploy/searxng/install.sh
```

- SearXNG は Python 3.11 以上が必要なので、`uv` で CPython 3.12 を `/opt/searxng` の中だけに入れる（システムの Python は変えない）。
- `127.0.0.1:8888` でだけ待ち受け、外からはアクセスできない。メモリは 70MB ほど。
- 使うエンジンは Google / Bing / DuckDuckGo / Wikipedia / Google News / Bing News / Yahoo News。Brave はすぐ利用制限がかかるので外している。
- 入れたら `/opt/mafuyu/.env` に `SEARXNG_URL=http://127.0.0.1:8888` を書いて bot を再起動する。

### 5. デプロイする（手元の PC から）

```bash
cp deploy/.deploy.env.example deploy/.deploy.env   # 接続先と SSH 鍵を書く（git 管理外）
bash deploy/deploy.sh
```

`deploy.sh` は git 管理下のファイルを VPS の `/opt/mafuyu/app` に送り、依存パッケージを入れて systemd サービスを再起動する。
`/opt/mafuyu/.env` がまだなければ、起動はしない。

## 運用

```bash
bash deploy/deploy.sh                         # コードやキャラ設定の変更を反映
ssh <vps> 'sudo journalctl -u mafuyu -f'      # ログ（返事ごとの利用額も出る）
ssh <vps> 'sudo systemctl restart mafuyu'     # 再起動（.env を変えたあと）
```

キャラの口調や性格は `character/system_prompt.md` を編集してデプロイするだけで変えられる。

## 設定（`.env`）

| キー | 既定値 | 説明 |
| --- | --- | --- |
| `DISCORD_TOKEN` | （必須） | Discord bot のトークン |
| `DEEPSEEK_API_KEY` | （必須） | DeepSeek の API キー |
| `ALLOWED_GUILD_IDS` | 空 | 反応するサーバー ID（カンマ区切り）。空なら招待されたすべてのサーバー |
| `DEEPSEEK_MODEL` | `deepseek-flash` | 使うモデル（`deepseek-v4-pro` も可） |
| `THINKING` | `0` | 思考モード（本番は `1`） |
| `THINKING_MAX_TOKENS` | `3000` | 思考モード時の出力上限（推論込み） |
| `TEMPERATURE` | `1.1` | 思考モードなしのときの温度 |
| `MAX_OUTPUT_TOKENS` | `600` | 思考モードなしのときの出力上限 |
| `HISTORY_LIMIT` | `20` | 文脈として読むチャンネルの直近メッセージ数 |
| `HISTORY_MAX_AGE_HOURS` | `12` | 何時間前までのメッセージを読むか |
| `SPEAKER_PAST_LIMIT` | `3` | 話しかけてきた人との過去のやりとりを何件読むか |
| `PROFILE_UPDATE_EVERY` | `3` | 何回会話したらプロファイルを更新するか |
| `USER_COOLDOWN_SEC` | `3` | 同じ人の連投を無視する秒数 |
| `ENABLE_WEB_SEARCH` | `1` | 調べものの道具（検索・URL・天気）を使うか |
| `SERPER_API_KEY` | 空 | Serper のキー（Google の検索結果。無料・カード不要で最初に 2,500 回）。空なら DuckDuckGo |
| `SEARXNG_URL` | 空 | VPS 内の SearXNG の URL（本番は `http://127.0.0.1:8888`）。Serper より先に使う |
| `DAILY_BUDGET_USD` | `0.1` | 1日の利用額の上限（0 で無制限） |
| `MONTHLY_BUDGET_USD` | `2` | 1か月の利用額の上限（0 で無制限） |
| `PRICE_INPUT_MISS` / `PRICE_INPUT_HIT` / `PRICE_OUTPUT` | `0.3` / `0.006` / `1.2` | 見積もりに使う単価（USD / 100万トークン、ピーク時） |
| `DATA_DIR` | `data/` | SQLite の保存先（VPS では `/opt/mafuyu/data`） |

## 開発

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .
```

テストは Discord や API に依存しない部分（メッセージの組み立て・無害化・記憶・予算）を対象にしている。
