#!/usr/bin/env python3
"""static/ のテンプレートから docs/ 一式（index.html・404.html・robots.txt・sitemap.xml・CNAME・CSS・JS・アセット）を作る。
docs/ は生成物なので手で直さない。docs/data/ は scripts/fetch_feeds.py の出力で、この build は触らない。
標準ライブラリのみ。実行: python3 build.py
"""
import json
import shutil
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
DOCS = ROOT / "docs"

TITLE = "ニュースポチ｜ブログの新着を、まとめて読む"
NAME = "ニュースポチ"
TAGLINE = "ブログの新着を、まとめて読む"
DESC = ("ニュース系ブログのRSSをまとめて読めるサイト。Apple系・飲食レビュー系のブログの新着を、"
        "新しい順の1本のタイムラインで。読みたいブログだけを購読リストで選べます。")
DOMAIN = "news.netaful.jp"

# 関連サイト一覧（ファミレスポチのフッターと同じ並び・文言。末尾にファミレスポチを足している）。広告なしなので data-google-vignette は付けない
RELATED = [
    ("https://book.netaful.jp/", "電書ポチ", "Kindle本セール"),
    ("https://kaden.netaful.jp/", "家電ポチ", "ガジェット・家電セール"),
    ("https://apple.netaful.jp/", "林檎ポチ", "Apple整備済製品"),
    ("https://manga.netaful.jp/", "漫画ポチ", "Webマンガ横断検索"),
    ("https://shinkan.netaful.jp/", "マンガ新刊ポチ", "コミック新刊の発売日をまとめて"),
    ("https://conbini.netaful.jp/", "コンビニポチ", "コンビニ新商品アーカイブ"),
    ("https://fastfood.netaful.jp/", "ファストフードポチ", "ファストフード限定メニュー"),
    ("https://cafe.netaful.jp/", "カフェポチ", "カフェの季節限定メニュー"),
    ("https://sushi.netaful.jp/", "回転寿司ポチ", "回転寿司の期間限定ネタ"),
    ("https://cupmen.netaful.jp/", "カップ麺ポチ", "カップ麺の新商品"),
    ("https://hotel.netaful.jp/", "ホテルポチ", "空室ホテルを安い順に検索"),
    ("https://onsen.netaful.jp/", "温泉宿ポチ", "温泉地の空室を、すぐ探す"),
    ("https://ritou.netaful.jp/", "離島宿ポチ", "島の空室を、すぐ探す"),
    ("https://michinoeki.netaful.jp/", "道の駅ポチ", "道の駅の駐車場と設備"),
    ("https://shinhatsubai.netaful.jp/", "新発売ポチ", "新商品を発売日でまとめて"),
    ("https://famires.netaful.jp/", "ファミレスポチ", "ファミレスの期間限定フェア"),
]


def load_config():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def ga_tag(ga_id):
    if not ga_id:
        return ""
    g = escape(ga_id)
    return (f'<script async src="https://www.googletagmanager.com/gtag/js?id={g}"></script>\n'
            "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
            f"gtag('js',new Date());gtag('config','{g}');</script>\n")


def head(config, title, desc, canonical, extra=""):
    base = config["site_url"]
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{ga_tag(config.get("ga4_id", ""))}<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="icon" type="image/png" sizes="96x96" href="/assets/favicon.png">
<link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:title" content="{escape(title)}">
<meta property="og:description" content="{escape(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="{NAME}">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{base}assets/ogp.jpg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/static/style.css">
{extra}</head>
<body>
"""


def header(tag):
    return f"""<header class="site-header">
<{tag} class="site-title"><a href="/"><img src="/assets/logo.png" alt="" width="44" height="44">{NAME}</a></{tag}>
<p class="tagline">{TAGLINE}</p>
</header>
"""


def footer(config):
    req = config.get("request_form_url", "")
    req_html = (f'<p><a href="{escape(req)}" target="_blank" rel="noopener">ブログの追加をリクエストする</a></p>\n'
                if req else "")
    links = "\n".join(
        f'<a href="{u}">{escape(n)}<span class="lbl"> {escape(d)}</span></a>' for u, n, d in RELATED)
    return f"""<footer class="site-footer">
<p>当サイトは各ブログの記事タイトルと概要の一部を表示し、元記事へリンクしています。各記事の権利は各ブログに帰属します。</p>
<p>Googleアナリティクス（Cookie）を利用しています。</p>
{req_html}<nav class="sites"><span class="lbl">関連サイト</span>
{links}
</nav>
<nav class="sites"><span class="lbl">ポチシリーズ一覧：</span>
<a href="https://pochi.netaful.jp/">ポチフル</a>
</nav>
</footer>
"""


def main_html(config):
    req = config.get("request_form_url", "")
    req_html = (f'<p class="np-request"><a href="{escape(req)}" target="_blank" rel="noopener">読みたいブログの追加をリクエストする</a></p>\n'
                if req else "")
    return f"""<main>
<div class="np-tabs" role="tablist" aria-label="表示の切り替え">
<button type="button" role="tab" class="np-tab" id="tab-home" data-view="home" aria-selected="true" aria-controls="view-home">ホーム</button>
<button type="button" role="tab" class="np-tab" id="tab-subs" data-view="subs" aria-selected="false" aria-controls="view-subs" tabindex="-1">購読リスト</button>
</div>
<div id="view-home" role="tabpanel" aria-labelledby="tab-home">
<div class="np-chips" id="np-chips" role="group" aria-label="系統で絞り込む"></div>
<p class="np-status" id="home-status" role="status">読み込み中…</p>
<ul class="np-list" id="home-list"></ul>
<p class="np-updated" id="home-updated"></p>
<noscript><p>このページの表示にはJavaScriptが必要です。</p></noscript>
</div>
<div id="view-subs" role="tabpanel" aria-labelledby="tab-subs" hidden>
<h2>読むブログを選ぶ</h2>
<div id="subs-groups"></div>
<button type="button" class="np-btn np-reset" id="subs-reset">すべてオンに戻す</button>
<h2>秘密の呪文</h2>
<div class="np-spell">
<p>購読の設定を表す文字列です。別の端末のこのサイトに貼り付けると、同じ設定にできます。</p>
<div class="np-spell-row">
<input type="text" id="spell-current" readonly aria-label="現在の呪文">
<button type="button" class="np-btn" id="spell-copy">コピー</button>
</div>
<div class="np-spell-row">
<input type="text" id="spell-input" placeholder="呪文を貼り付け" aria-label="読み込む呪文" autocomplete="off" spellcheck="false">
<button type="button" class="np-btn" id="spell-load">読み込む</button>
</div>
<p class="np-msg" id="spell-msg" role="status"></p>
</div>
{req_html}</div>
</main>
"""


def build_index(config):
    ld = {"@context": "https://schema.org", "@type": "WebSite", "name": NAME, "url": config["site_url"]}
    extra = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False, separators=(",", ":"))}</script>\n'
    return (head(config, TITLE, DESC, config["site_url"], extra) + header("h1") + main_html(config)
            + footer(config)
            + '<script src="/static/app.js" defer></script>\n</body>\n</html>\n')


def build_404(config):
    body = ('<main>\n<h2>ページが見つかりません</h2>\n<p>お探しのページは見つかりませんでした。'
            f'<a href="/">{NAME}のトップ</a>から、ブログの新着をご覧ください。</p>\n</main>\n')
    return (head(config, f"ページが見つかりません｜{NAME}", "お探しのページは見つかりませんでした。",
                 config["site_url"] + "404.html", '<meta name="robots" content="noindex">\n')
            + header("div") + body + footer(config) + "</body>\n</html>\n")


def main():
    config = load_config()
    (DOCS / "static").mkdir(parents=True, exist_ok=True)
    for f in ("style.css", "app.js"):
        shutil.copy2(ROOT / "static" / f, DOCS / "static" / f)
    assets = ROOT / "static/assets"
    if assets.is_dir():
        shutil.copytree(assets, DOCS / "assets", dirs_exist_ok=True)
    (DOCS / "index.html").write_text(build_index(config), encoding="utf-8")
    (DOCS / "404.html").write_text(build_404(config), encoding="utf-8")
    (DOCS / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {config['site_url']}sitemap.xml\n", encoding="utf-8")
    (DOCS / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"<url><loc>{config['site_url']}</loc></url>\n</urlset>\n", encoding="utf-8")
    (DOCS / "CNAME").write_text(DOMAIN + "\n", encoding="utf-8")
    print(f"built -> {DOCS}")


if __name__ == "__main__":
    main()
