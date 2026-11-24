"""fetch_feeds.py の検証。ネットワークには出ない（Fetcher を偽物に差し替える）。"""
import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_feeds as ff  # noqa: E402

NOW = datetime.datetime(2026, 11, 24, 6, 0, 0, tzinfo=datetime.timezone.utc)

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel><title>t</title>
<item>
 <title>記事A &amp; B</title>
 <link>https://ex.com/a?utm_source=x&amp;id=1#frag</link>
 <pubDate>Tue, 24 Nov 2026 04:00:00 +0000</pubDate>
 <category>Mac</category><category>セール情報</category>
 <description>&lt;p&gt;本文 &amp;amp; &lt;b&gt;太字&lt;/b&gt;&lt;/p&gt;</description>
 <content:encoded><![CDATA[<p><img src="https://ex.com/body.jpg"> 本文</p>]]></content:encoded>
 <media:thumbnail url="https://ex.com/thumb.jpg"/>
</item>
<item>
 <title>画像は media:content</title>
 <link>https://ex.com/b</link>
 <dc:date>2026-11-23T10:00:00+09:00</dc:date>
 <media:content url="https://ex.com/mc.jpg" medium="image"/>
 <enclosure url="https://ex.com/enc.jpg" type="image/jpeg"/>
 <description>b</description>
</item>
<item>
 <title>画像は enclosure</title>
 <link>https://ex.com/c</link>
 <enclosure url="https://ex.com/enc.jpg" type="image/jpeg"/>
 <description>c</description>
</item>
<item>
 <title>画像は本文の img</title>
 <link>https://ex.com/d</link>
 <pubDate>Tue, 24 Nov 2026 03:00:00 +0000</pubDate>
 <content:encoded><![CDATA[<img src="javascript:alert(1)"><img src='//cdn.ex.com/first.png'>]]></content:encoded>
</item>
<item>
 <title>未来の日付</title>
 <link>https://ex.com/e</link>
 <pubDate>Fri, 01 Jan 2027 00:00:00 +0000</pubDate>
</item>
<item><title></title><link>https://ex.com/notitle</link></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
<title>t</title>
<entry>
 <title>アトム記事</title>
 <link rel="replies" href="https://ex.com/replies"/>
 <link rel="alternate" href="https://ex.com/atom1"/>
 <published>2026-11-24T05:00:00Z</published>
 <category term="飲食"/>
 <summary>要約です</summary>
 <content type="html">&lt;p&gt;&lt;img src="https://ex.com/atom.jpg"/&gt;長い本文&lt;/p&gt;</content>
</entry>
</feed>"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        if v is None or isinstance(v, Exception):
            raise v or ff.FetchError("404")
        return v.encode("utf-8")


def cfg(**kw):
    return {"retention_days": 7, **kw}


def bundle(*blogs):
    return {"categories": [{"id": "c", "name": "C", "order": 1}], "blogs": list(blogs)}


def blog(id_, feeds, exclude=()):
    return {"id": id_, "name": id_, "category": "c", "site_url": "https://ex.com/", "feeds": list(feeds),
            "exclude_categories": list(exclude)}


def art(url, blog_id, published, **kw):
    return {"url": url, "title": "t", "blog": blog_id, "published": published, "summary": "", "image": None, **kw}


class ParseTest(unittest.TestCase):
    def test_rss_normalization(self):
        items = ff.parse_feed(RSS.encode("utf-8"))
        self.assertEqual(len(items), 5)  # タイトル無しは捨てる
        a = items[0]
        self.assertEqual(a["title"], "記事A & B")
        self.assertEqual(a["url"], "https://ex.com/a?id=1")  # utm_* とフラグメントを落とす
        self.assertEqual(a["summary"], "本文 & 太字")
        self.assertEqual(a["categories"], ["Mac", "セール情報"])
        self.assertEqual(a["published"], datetime.datetime(2026, 11, 24, 4, 0, tzinfo=datetime.timezone.utc))
        self.assertEqual(items[1]["published"], datetime.datetime(2026, 11, 23, 1, 0, tzinfo=datetime.timezone.utc))  # dc:date

    def test_image_priority(self):
        a, b, c, d, _ = ff.parse_feed(RSS.encode("utf-8"))
        self.assertEqual(a["image"], "https://ex.com/thumb.jpg")   # thumbnail が本文imgに勝つ
        self.assertEqual(b["image"], "https://ex.com/mc.jpg")      # media:content が enclosure に勝つ
        self.assertEqual(c["image"], "https://ex.com/enc.jpg")
        self.assertEqual(d["image"], "https://cdn.ex.com/first.png")  # javascript: は飛ばして次のimg

    def test_atom(self):
        (e,) = ff.parse_feed(ATOM.encode("utf-8"))
        self.assertEqual(e["url"], "https://ex.com/atom1")  # rel=alternate を選ぶ
        self.assertEqual(e["summary"], "要約です")
        self.assertEqual(e["categories"], ["飲食"])
        self.assertEqual(e["image"], "https://ex.com/atom.jpg")

    def test_summary_truncation(self):
        s = ff.make_summary("<p>" + "あ" * 200 + "</p>")
        self.assertEqual(s, "あ" * 120 + "…")
        self.assertEqual(ff.make_summary("<style>x{}</style>  a \n b "), "a b")

    def test_broken_xml(self):
        with self.assertRaises(ValueError):
            ff.parse_feed(b"<rss><channel><item>")
        with self.assertRaises(ValueError):
            ff.parse_feed(b"<html></html>")

    def test_exclude_partial_match(self):
        self.assertTrue(ff.is_excluded(["Mac", "Amazonセール情報"], ["セール"]))
        self.assertFalse(ff.is_excluded(["Mac"], ["セール"]))
        self.assertFalse(ff.is_excluded(["セール"], []))


class RunTest(unittest.TestCase):
    def run_(self, pages, blogs, existing=(), old_status=None):
        f = FakeFetcher(pages)
        out = ff.run(cfg(), bundle(*blogs), f, list(existing), old_status or {}, NOW)
        return out, f

    def test_exclude_rule_applied(self):
        (arts, st, _), _ = self.run_({"u1": RSS}, [blog("a", ["u1"], exclude=["セール"])])
        urls = [x["url"] for x in arts]
        self.assertNotIn("https://ex.com/a?id=1", urls)
        self.assertEqual(st["blogs"]["a"]["excluded"], 1)

    def test_fields_and_future_clamp(self):
        (arts, st, _), _ = self.run_({"u1": RSS}, [blog("a", ["u1"])])
        e = next(x for x in arts if x["url"] == "https://ex.com/e")
        self.assertEqual(e["published"], "2026-11-24T06:00:00Z")  # 1日以上先は取得時刻
        c = next(x for x in arts if x["url"] == "https://ex.com/c")
        self.assertEqual(c["published"], "2026-11-24T06:00:00Z")  # 日付なしは取得時刻
        self.assertEqual(set(c), {"url", "title", "blog", "published", "summary", "image"})
        self.assertEqual(st["blogs"]["a"]["with_image"], 4)

    def test_multi_feed_dedup_and_global_priority(self):
        pages = {"u1": RSS, "u2": RSS, "u3": ATOM}
        (arts, st, _), _ = self.run_(pages, [blog("a", ["u1", "u2"]), blog("b", ["u3"])])
        urls = [x["url"] for x in arts]
        self.assertEqual(len(urls), len(set(urls)))
        # 2本目の同内容フィードで二重にならない
        self.assertEqual(st["blogs"]["a"]["fetched"], 5)
        # 別ブログに同じURLがあれば先に登録されたブログが勝つ
        (arts2, _, _), _ = self.run_({"u1": ATOM, "u2": ATOM}, [blog("a", ["u1"]), blog("b", ["u2"])])
        self.assertEqual([x["blog"] for x in arts2], ["a"])

    def test_retention_cut(self):
        old = [art("https://ex.com/old", "a", "2026-11-10T00:00:00Z"), art("https://ex.com/ok", "a", "2026-11-20T00:00:00Z")]
        (arts, _, _), _ = self.run_({"u1": ATOM}, [blog("a", ["u1"])], existing=old)
        urls = [x["url"] for x in arts]
        self.assertNotIn("https://ex.com/old", urls)
        self.assertIn("https://ex.com/ok", urls)
        self.assertEqual(urls[0], "https://ex.com/atom1")  # 新しい順

    def test_one_feed_failure_keeps_others_and_existing(self):
        existing = [art("https://ex.com/keep", "b", "2026-11-22T00:00:00Z")]
        old_status = {"blogs": {"b": {"last_success": "2026-11-23T00:00:00Z"}}}
        pages = {"u1": ATOM, "u2": ff.FetchError("HTTP 500"), "u3": "<rss><broken"}
        (arts, st, _), _ = self.run_(pages, [blog("a", ["u1"]), blog("b", ["u2"]), blog("c", ["u3"])], existing, old_status)
        urls = [x["url"] for x in arts]
        self.assertIn("https://ex.com/atom1", urls)      # 他のブログは出る
        self.assertIn("https://ex.com/keep", urls)       # 失敗したブログの既存記事は残る
        self.assertIsNone(st["blogs"]["a"]["last_error"])
        self.assertIn("HTTP 500", st["blogs"]["b"]["last_error"])
        self.assertEqual(st["blogs"]["b"]["last_success"], "2026-11-23T00:00:00Z")  # 前回の成功時刻を保つ
        self.assertIn("XML", st["blogs"]["c"]["last_error"])
        self.assertIsNone(st["blogs"]["c"]["last_success"])

    def test_partial_feed_failure_counts_success(self):
        pages = {"u1": ATOM, "u2": ff.FetchError("HTTP 500")}
        (arts, st, _), _ = self.run_(pages, [blog("a", ["u1", "u2"])])
        self.assertEqual(len(arts), 1)
        self.assertEqual(st["blogs"]["a"]["feeds_ok"], 1)
        self.assertIsNotNone(st["blogs"]["a"]["last_error"])
        self.assertEqual(st["blogs"]["a"]["last_success"], "2026-11-24T06:00:00Z")

    def test_removed_blog_articles_dropped(self):
        existing = [art("https://ex.com/gone", "zzz", "2026-11-23T00:00:00Z")]
        (arts, _, _), _ = self.run_({"u1": ATOM}, [blog("a", ["u1"])], existing)
        self.assertNotIn("https://ex.com/gone", [x["url"] for x in arts])

    def test_public_blogs_has_no_feeds(self):
        (_, _, pub), _ = self.run_({"u1": ATOM}, [blog("a", ["u1"])])
        self.assertNotIn("feeds", pub["blogs"][0])
        self.assertEqual(pub["categories"][0]["id"], "c")


class MainTest(unittest.TestCase):
    def test_main_writes_and_skips_unchanged(self):
        import os
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            ff.main(fetcher=FakeFetcher({u: ATOM for u in self._urls()}), now=NOW, data_dir=d)
            first = (d / "articles.json").read_bytes()
            self.assertTrue((d / "status.json").exists() and (d / "blogs.json").exists())
            later = NOW + datetime.timedelta(hours=1)
            ff.main(fetcher=FakeFetcher({u: ATOM for u in self._urls()}), now=later, data_dir=d)
            self.assertEqual((d / "articles.json").read_bytes(), first)  # 中身が同じなら書き換えない
            self.assertEqual(json.loads(first)["articles"][0]["url"], "https://ex.com/atom1")

    def _urls(self):
        b = json.loads((Path(__file__).resolve().parent.parent / "data/blogs.json").read_text(encoding="utf-8"))
        return [u for x in b["blogs"] for u in x["feeds"]]


class FetcherTest(unittest.TestCase):
    def test_robots_checked_once_per_host_and_denied(self):
        sleeps = []
        f = ff.Fetcher({"user_agent": "NewsPochi/1.0", "request_interval_sec": 2}, sleep=sleeps.append)
        calls = []

        def raw(url):
            calls.append(url)
            if url.endswith("/robots.txt"):
                return b"User-agent: *\nDisallow: /private/\n"
            return b"<rss/>"
        f._raw = raw
        self.assertEqual(f.get("https://h.com/feed"), b"<rss/>")
        self.assertEqual(f.get("https://h.com/feed2"), b"<rss/>")
        with self.assertRaises(ff.FetchError):
            f.get("https://h.com/private/x")
        self.assertEqual(calls.count("https://h.com/robots.txt"), 1)

    def test_robots_unreachable_means_allowed_and_interval(self):
        sleeps = []
        f = ff.Fetcher({"user_agent": "NewsPochi/1.0", "request_interval_sec": 2}, sleep=sleeps.append)
        import urllib.error
        orig = ff.urllib.request.urlopen

        class R:
            def __init__(s, d): s.d = d
            def read(s, n): return s.d
            def __enter__(s): return s
            def __exit__(s, *a): return False

        def fake(req, timeout=None):
            if req.full_url.endswith("/robots.txt"):
                raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, __import__("io").BytesIO(b""))
            self.assertEqual(req.get_header("User-agent"), "NewsPochi/1.0")
            return R(b"ok")
        ff.urllib.request.urlopen = fake
        try:
            self.assertEqual(f.get("https://h.com/feed"), b"ok")
        finally:
            ff.urllib.request.urlopen = orig
        self.assertEqual(sleeps, [2.0])  # 2回目のリクエスト（本体）の前だけ空ける


if __name__ == "__main__":
    unittest.main()
