#!/usr/bin/env python3
"""data/blogs.json の全フィードを取得し、docs/data/articles.json と status.json と blogs.json を書く。
標準ライブラリのみ。実行: python3 scripts/fetch_feeds.py

取得の作法: 正直なUA・1リクエストごとに request_interval_sec 空ける・robots.txt をホストごとに1回だけ確認する。
1フィードの失敗で全体は止めない（失敗したブログの既存記事は残す）。
"""
import datetime
import email.utils
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = ROOT / "docs/data"
SUMMARY_MAX = 120
ROBOTS_TOKEN = "NewsPochi"


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------- 取得

class FetchError(Exception):
    pass


class Fetcher:
    """UA・間隔・サイズ上限・robots.txt を守る取得役。テストではこのクラスごと差し替える
    （必要なのは get(url) -> bytes だけ。失敗は FetchError）。"""

    def __init__(self, config, sleep=time.sleep):
        self.ua = config["user_agent"]
        self.interval = float(config.get("request_interval_sec", 2))
        self.timeout = float(config.get("timeout_sec", 20))
        self.max_bytes = int(config.get("max_bytes", 5 * 1024 * 1024))
        self._sleep = sleep
        self._first = True
        self._robots = {}

    def _raw(self, url):
        if not self._first:
            self._sleep(self.interval)
        self._first = False
        req = urllib.request.Request(url, headers={"User-Agent": self.ua, "Accept": "application/xml, text/xml, */*"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read(self.max_bytes + 1)
        except urllib.error.HTTPError as e:
            e.close()
            raise FetchError(f"HTTP {e.code}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise FetchError(f"取得失敗: {e}") from e
        if len(data) > self.max_bytes:
            raise FetchError("サイズ上限を超えた")
        return data

    def _allowed(self, url):
        p = urllib.parse.urlsplit(url)
        host = f"{p.scheme}://{p.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                body = self._raw(host + "/robots.txt").decode("utf-8", "replace")
                rp.parse(body.splitlines())
            except FetchError:  # 取れない・4xx は「制限なし」扱い
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return rp is None or rp.can_fetch(ROBOTS_TOKEN, url)

    def get(self, url):
        if not self._allowed(url):
            raise FetchError("robots.txt で拒否されている")
        return self._raw(url)


# ---------------------------------------------------------------- 解析

def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def children(el, name):
    return [c for c in el if local(c.tag) == name]


def first_text(el, *names):
    for n in names:
        for c in children(el, n):
            t = "".join(c.itertext()).strip()
            if t:
                return t
    return ""


def normalize_url(u):
    """utm_* とフラグメントを落とす。"""
    p = urllib.parse.urlsplit(u.strip())
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def is_http(u):
    return isinstance(u, str) and re.match(r"^https?://", u, re.I) is not None


def clean_text(h):
    h = re.sub(r"(?is)<(script|style)\b.*?</\1\s*>", " ", h or "")
    h = re.sub(r"<[^>]*>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(h)).strip()


def make_summary(h):
    t = clean_text(h)
    return t if len(t) <= SUMMARY_MAX else t[:SUMMARY_MAX] + "…"


def first_img(h):
    for m in re.finditer(r"(?is)<img\b[^>]*?\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", h or ""):
        src = html.unescape(m.group(1) or m.group(2) or "").strip()
        if src.startswith("//"):
            src = "https:" + src
        if is_http(src):
            return src
    return None


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    dt = None
    try:
        dt = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        dt = None
    if dt is None:
        try:
            dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def find_image(item, body_html):
    for c in item:
        if local(c.tag) == "thumbnail" and is_http(c.get("url")):
            return c.get("url").strip()
    for c in item:
        if local(c.tag) == "content" and c.get("url") and (
                c.get("medium") == "image" or (c.get("type") or "").startswith("image/")):
            if is_http(c.get("url")):
                return c.get("url").strip()
    for c in item:
        if local(c.tag) == "enclosure" and (c.get("type") or "").startswith("image/") and is_http(c.get("url")):
            return c.get("url").strip()
    for c in item:  # Atom の rel=enclosure
        if local(c.tag) == "link" and c.get("rel") == "enclosure" and (c.get("type") or "").startswith("image/") \
                and is_http(c.get("href")):
            return c.get("href").strip()
    return first_img(body_html)


def parse_feed(data):
    """RSS 2.0 / Atom のバイト列 → 生の記事の配列。XML が壊れていたら ValueError。
    各要素: url, title, published(datetime|None), summary, image, categories。"""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise ValueError(f"XMLが壊れている: {e}") from e
    kind = local(root.tag)
    if kind == "rss" or kind == "RDF":
        items = [i for i in root.iter() if local(i.tag) == "item"]
    elif kind == "feed":
        items = children(root, "entry")
    else:
        raise ValueError(f"RSS/Atomではない: <{kind}>")
    out = []
    for it in items:
        url = ""
        if kind == "feed":
            links = children(it, "link")
            alt = [l for l in links if l.get("rel") in (None, "alternate")]
            url = (alt[0].get("href") if alt else "") or ""
        else:
            url = first_text(it, "link")
            if not is_http(url):
                g = first_text(it, "guid")
                url = g if is_http(g) else ""
        url = url.strip()
        title = clean_text(first_text(it, "title"))
        if not is_http(url) or not title:
            continue
        # 本文: 要約には description / summary を優先し、無ければ content。画像探しには両方を使う
        desc = first_text(it, "description", "summary")
        full = first_text(it, "content") if kind == "feed" else first_text(it, "encoded")
        cats = []
        for c in children(it, "category"):
            v = c.get("term") or "".join(c.itertext())
            if v and v.strip():
                cats.append(v.strip())
        for c in children(it, "subject"):  # dc:subject
            v = "".join(c.itertext()).strip()
            if v:
                cats.append(v)
        date = parse_date(first_text(it, "pubDate", "published", "updated", "date"))
        out.append({
            "url": normalize_url(url),
            "title": title,
            "published": date,
            "summary": make_summary(desc or full),
            "image": find_image(it, (full or "") + "\n" + (desc or "")),
            "categories": cats,
        })
    return out


def strip_suffix(title, suffix):
    """タイトル末尾の決まった文字列（例: 「｜キャプテン福田」）を落とす。suffix は文字列か文字列の配列で、
    配列なら前から順に試して最初に一致したものを落とす（長いものを先に書く）。落とすと空になるなら元のまま。"""
    for s in ([suffix] if isinstance(suffix, str) else (suffix or [])):
        if s and title.endswith(s) and title[:-len(s)].strip():
            return title[:-len(s)].rstrip()
    return title


def is_excluded(cats, words):
    return any(w and w in c for c in cats for w in words)


# ---------------------------------------------------------------- 合流

def merge(blogs, fresh_by_blog, existing, now, retention_days):
    """fresh_by_blog: {blog_id: [記事dict]}、existing: 前回の記事の配列。
    記事URLで全体を重複排除（blogs の並び＝登録順を優先、同じブログ内は新しい取得を優先）、
    retention_days より古いものを落として新しい順に返す。"""
    order = {b["id"]: i for i, b in enumerate(blogs)}
    cands = []
    for b in blogs:
        cands.extend(fresh_by_blog.get(b["id"], []))
    cands.extend(a for a in existing if a.get("blog") in order and is_http(a.get("url")))
    cands.sort(key=lambda a: order[a["blog"]])  # 安定ソート: 同じブログでは fresh が existing より先
    seen, out = set(), []
    cutoff = iso(now - datetime.timedelta(days=retention_days))
    for a in cands:
        key = normalize_url(a["url"])
        if key in seen:
            continue
        seen.add(key)
        if a["published"] < cutoff:
            continue
        out.append(a)
    out.sort(key=lambda a: (a["published"], a["url"]), reverse=True)
    return out


def run(config, bundle, fetcher, existing_articles, old_status, now):
    """取得して (articles, status, public_blogs) を返す。ファイルには書かない。"""
    blogs = bundle["blogs"]
    fresh, status = {}, {}
    # 絞り込み・除外で落とした記事URL。ルールを足す前に保存済みの同じ記事も、今回のフィードに
    # 載っていればすぐ消す（フィードから外れた古い記事は7日切りで自然に消える）
    dropped = set()
    # URL指定の除外（固定記事など）。取得分にも保存済みの記事にも効かせる
    skip_urls = {b["id"]: {normalize_url(u) for u in b.get("exclude_urls", [])} for b in blogs}
    existing_articles = [a for a in (existing_articles or [])
                         if normalize_url(a.get("url", "")) not in skip_urls.get(a.get("blog"), set())]
    # タイトル末尾の決まり文句は、保存済みの記事にもすぐ効かせる
    suffix = {b["id"]: b.get("title_suffix", "") for b in blogs}
    existing_articles = [{**a, "title": strip_suffix(a.get("title", ""), suffix.get(a.get("blog"), ""))}
                         for a in existing_articles]
    for b in blogs:
        prev = (old_status or {}).get("blogs", {}).get(b["id"], {})
        errors, ok_count, kept, excluded, imgs = [], 0, [], 0, 0
        for feed in b["feeds"]:
            try:
                raw = parse_feed(fetcher.get(feed))
            except (FetchError, ValueError) as e:
                errors.append(f"{feed}: {e}")
                continue
            ok_count += 1
            for r in raw:
                include = b.get("include_categories") or []
                if (include and not is_excluded(r["categories"], include)) \
                        or is_excluded(r["categories"], b.get("exclude_categories", [])) or r["url"] in skip_urls[b["id"]]:
                    excluded += 1
                    dropped.add(r["url"])
                    continue
                pub = r["published"] or now
                if pub > now + datetime.timedelta(days=1):
                    pub = now
                kept.append({"url": r["url"], "title": strip_suffix(r["title"], b.get("title_suffix", "")), "blog": b["id"], "published": iso(pub),
                             "summary": r["summary"], "image": r["image"]})
        # ブログ内（複数フィード間）の重複を落とす
        uniq, seen = [], set()
        for a in kept:
            if a["url"] not in seen:
                seen.add(a["url"])
                uniq.append(a)
        fresh[b["id"]] = uniq
        status[b["id"]] = {
            "last_success": iso(now) if ok_count else prev.get("last_success"),
            "last_error": "; ".join(errors) if errors else None,
            "feeds_ok": ok_count,
            "feeds_total": len(b["feeds"]),
            "fetched": len(uniq),
            "excluded": excluded,
            "with_image": sum(1 for a in uniq if a["image"]),
        }
    existing_articles = [a for a in existing_articles if normalize_url(a.get("url", "")) not in dropped]
    articles = merge(blogs, fresh, existing_articles, now, config.get("retention_days", 7))
    public = {
        "categories": sorted(bundle["categories"], key=lambda c: c["order"]),
        "blogs": [{"id": b["id"], "name": b["name"], "category": b["category"], "site_url": b["site_url"],
                   **({"yomi": b["yomi"]} if b.get("yomi") else {})} for b in blogs],
    }
    return articles, {"generated": iso(now), "blogs": status}, public


def _stable(obj):
    """タイムスタンプを除いた比較用の形。"""
    o = json.loads(json.dumps(obj))
    o.pop("generated", None)
    for s in o.get("blogs", {}).values() if isinstance(o.get("blogs"), dict) else []:
        s.pop("last_success", None)
    return o


def write_if_changed(path, obj, stable=False):
    old = load_json(path)
    if old is not None and (_stable(old) == _stable(obj) if stable else old == obj):
        return False
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def main(fetcher=None, now=None, data_dir=DOCS_DATA):
    config = load_json(ROOT / "config.json")
    bundle = load_json(ROOT / "data/blogs.json")
    # enabled: false のブログは掲載をやめる（購読リストからも消え、記事も次の実行で消える。id は欠番として残す）
    bundle = {**bundle, "blogs": [b for b in bundle["blogs"] if b.get("enabled", True)]}
    now = now or datetime.datetime.now(datetime.timezone.utc)
    fetcher = fetcher or Fetcher(config)
    old = load_json(data_dir / "articles.json", {}) or {}
    old_status = load_json(data_dir / "status.json", {}) or {}
    articles, status, public = run(config, bundle, fetcher, old.get("articles", []), old_status, now)
    write_if_changed(data_dir / "articles.json", {"generated": iso(now), "articles": articles}, stable=True)
    write_if_changed(data_dir / "status.json", status, stable=True)
    write_if_changed(data_dir / "blogs.json", public)
    for b in bundle["blogs"]:
        s = status["blogs"][b["id"]]
        print(f"{b['id']}: 取得{s['fetched']} 画像あり{s['with_image']} 除外{s['excluded']} "
              f"フィード{s['feeds_ok']}/{s['feeds_total']}" + (f" エラー: {s['last_error']}" if s["last_error"] else ""))
    print(f"記事 計{len(articles)}件")
    return articles, status


if __name__ == "__main__":
    main()
    sys.exit(0)
