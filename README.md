# ニュースポチ

https://news.netaful.jp/ — ニュース系ブログのRSSを系統別（Apple系・飲食レビュー系）に集約して読む静的サイト。ポチシリーズの1つ。
記事のタイトル・概要（120字まで）・サムネイルURL・日時だけを持ち、本文は保存しない。元記事へは別タブでリンクする。

仕組み：Cloud Scheduler が1時間ごとに GitHub Actions（`update.yml`）を dispatch → `scripts/fetch_feeds.py` が全フィードを取得して `docs/data/*.json` を更新 → `build.py` が `docs/` を生成 → 変更があればコミット＆push → GitHub Pages が配信。画面は `docs/data/*.json` を読んで表示する（`static/app.js`）。

## ファイル構成

| パス | 役割 |
|---|---|
| `config.json` | site_url・ga4_id・request_form_url・retention_days・取得の作法（間隔・タイムアウト・サイズ上限・UA） |
| `data/blogs.json` | 系統（categories）とブログ（blogs）の定義。**手で編集するのはここ** |
| `scripts/fetch_feeds.py` | フィード取得→正規化→前回分と合流→`docs/data/` 出力（標準ライブラリのみ） |
| `build.py` | `static/` から `docs/`（HTML・CSS・JS・アセット・robots・sitemap・CNAME）を生成 |
| `static/app.js`, `static/style.css` | 画面。`app.js` 前半は純粋関数（呪文・購読モデル・絞り込み・日時） |
| `static/assets/` | アイコン・OGP。元は `~/Desktop/Claude/pochi-branding` の `python3 make_branding.py news`（配置先をここに向けてある） |
| `docs/` | **生成物。手で直さない**。`docs/data/articles.json`・`status.json`・`blogs.json` は fetch の出力 |
| `tests/` | `python3 -m unittest discover -s tests`（JSのテストは macOS の osascript が必要。無ければスキップ） |
| `.github/workflows/update.yml` | 更新（workflow_dispatch のみ） |
| `.github/workflows/test.yml` | push・PR でテスト |

## 運用手順

### ① ブログ・フィードの追加

`data/blogs.json` の `blogs` に1件足す。

```json
{
 "id": "example-blog",
 "name": "表示名",
 "category": "apple",
 "site_url": "https://example.com/",
 "feeds": ["https://example.com/feed"],
 "exclude_categories": []
}
```

- **`id` は英小文字・数字・ハイフンだけ。一度決めたら変えない・使い回さない。** 利用者の購読設定（cookie `np_sub` と「秘密の呪文」）に入っているため、変えると購読が壊れる。不要になったブログは `blogs` から消す（呪文に残っていても読み込み時に黙って捨てられる）。
- `category` は `categories` の `id`。
- 1ブログに複数フィードを束ねられる（ネタフルApple系は4本）。重複は記事URL（`utm_*` を除いた形）で排除。全体でも同じURLは1件にし、`blogs` で先に書いたブログが優先。
- 並び：購読リストの系統内の順は `blogs` の並び。重複時の優先もこの並び。
- 新しいブログは、全部モードの利用者には自動で入り、カスタムモードの利用者にはオフで出る。
- 系統の追加：`categories` に `{"id": "tech", "name": "テック系", "order": 3}` を足し、ブログの `category` に使う。`order` が表示順。
- 追加後は手元で `python3 scripts/fetch_feeds.py && python3 build.py` を1回流し、`docs/data/status.json` の `last_error` が `null` か確認する。
- 注意：ネタフルのカテゴリ別フィードは `/eat/feed` のほか `/neta-eat/`・`/fast-food/` のようなスラッグもある（2026-11-24 時点で `/eat/feed` の最新は11/3だった）。フィードURLは実物を確認してから書く。

### ② 除外ルール

`exclude_categories` に語の配列を書く。記事のカテゴリ（RSSの `<category>`、Atomの `<category term>`）の**どれか**に、いずれかの語が**含まれていたら**（部分一致）その記事を落とす。例：ゴリミーは `["セール"]` で「Amazonセール情報」なども落ちる。

効くのは取得時だけ。ルールを足す前に保存済みの記事は、7日で自然に消えるまで残る。

### ③ 手動実行

- `gh workflow run update.yml -R netafull/news-pochi`
- GitHub の Actions 画面 → update → Run workflow
- 手元：`python3 scripts/fetch_feeds.py && python3 build.py`（`docs/` が更新される。コミット・push は別）

更新は Cloud Scheduler から1時間ごと（GitHub の schedule は欠測が多いので使わない）。ジョブ名の予定は `news-pochi-update`。

状態の確認：`docs/data/status.json` にブログごとの `last_success`・`last_error`・取得件数・除外件数・画像あり件数がある。1つのフィードが失敗しても他は更新され、失敗したブログの既存記事は7日まで残る。`articles.json` と `status.json` は、タイムスタンプ以外が前回と同じなら書き換えない（毎時の無駄なコミットを避けるため。画面の「データの最終更新」は記事データが変わった時刻）。

### ④ 呪文と cookie の仕様

- 購読は cookie `np_sub`（`Max-Age=31536000; Path=/; SameSite=Lax; Secure`）。値は呪文と同じ文字列。cookie が使えなければ毎回「全部モード」。
- 全部モード（初期状態）：その時点の全ブログが対象。後から増えたブログも自動で入る。呪文は `np1-all`。
- カスタムモード：購読リストのトグルを1つでも触ると移行。そのときの「オンのブログid一覧」を保存し、以後はそれだけが対象。呪文は `np1-` + base64url（パディングなし）で「カンマ区切りのブログid」をエンコードしたもの（例：`gorime,shingeki` → `np1-Z29yaW1lLHNoaW5nZWtp`）。「すべてオンに戻す」で全部モードに戻る。
- 読み込み時：未知のidは黙って捨てる。`np1-` で始まらない・base64urlとして読めない場合は失敗メッセージ。
- 画面の最後に開いたタブは localStorage `newspochi.view` に記憶（使えなくても動く）。
- 実装は `static/app.js` の `encodeSpell`/`decodeSpell`。形式を変えるときは `tests/test_app.py` も直す（バージョン接頭辞 `np1-` を上げる）。

### ⑤ 取得の作法

- UA：`NewsPochi/1.0 (+https://news.netaful.jp/)`（`config.json`）。偽装しない。
- 1リクエストごとに `request_interval_sec`（2秒）空ける（robots.txt の取得も1リクエストに数える）。タイムアウト20秒、1レスポンス5MBまで。
- robots.txt はホストごとに1回だけ確認（`NewsPochi` トークン）。取れない・4xx は「制限なし」扱い、拒否されたパスは取らない。
- 記事は `retention_days`（7日）より古いものを落とす。未来日時は、取得時刻より1日以上先なら取得時刻に直す。日付が読めない記事は取得時刻。
- 403・429 などで取れないときは回避せず、`status.json` に記録して次回に任せる。

## 記事の形（docs/data/articles.json）

`url`・`title`・`blog`（ブログid）・`published`（UTCのISO 8601）・`summary`（タグを落として120字、超えたら「…」）・`image`（media:thumbnail → media:content(image) → enclosure(image/*) → 本文の最初の`<img>`。http(s)のみ、なければ null）。
