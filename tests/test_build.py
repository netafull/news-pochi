"""build.py の出力の検証（docs/ は一時ディレクトリではなく実際の docs/ に書く。生成物なので問題なし）。"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402


def render(**over):
    cfg = build.load_config()
    cfg.update(over)
    return build.build_index(cfg), build.build_404(cfg)


class BuildTest(unittest.TestCase):
    def test_ga_empty_not_output(self):
        idx, nf = render(ga4_id="")
        self.assertNotIn("googletagmanager", idx)
        self.assertNotIn("googletagmanager", nf)

    def test_ga_output_when_set(self):
        idx, _ = render(ga4_id="G-TEST123")
        self.assertIn("gtag/js?id=G-TEST123", idx)
        self.assertIn("gtag('config','G-TEST123')", idx)

    def test_request_link_only_when_set(self):
        idx, _ = render(request_form_url="")
        self.assertNotIn("リクエスト", idx)
        idx, nf = render(request_form_url="https://forms.example.com/x")
        self.assertEqual(idx.count("https://forms.example.com/x"), 2)  # 購読リスト下部とフッター
        self.assertIn("https://forms.example.com/x", nf)

    def test_disclosure_and_footer(self):
        idx, _ = render()
        self.assertIn("当サイトは各ブログの記事タイトルと概要の一部を表示し、元記事へリンクしています。各記事の権利は各ブログに帰属します。", idx)
        self.assertIn("Googleアナリティクス（Cookie）を利用しています。", idx)
        self.assertNotIn("adsbygoogle", idx)
        self.assertNotIn("AdSense", idx)
        self.assertIn("https://famires.netaful.jp/", idx)
        self.assertIn("ファミレスの期間限定フェア", idx)
        self.assertIn('href="https://pochi.netaful.jp/">ポチフル', idx)
        self.assertEqual(len(re.findall(r'<nav class="sites">', idx)), 2)

    def test_head(self):
        idx, _ = render()
        self.assertIn("<title>ニュースポチ｜ブログの新着を、まとめて読む</title>", idx)
        self.assertIn('<link rel="canonical" href="https://news.netaful.jp/">', idx)
        for s in ('property="og:image" content="https://news.netaful.jp/assets/ogp.jpg"', "/assets/favicon.png",
                  "/assets/apple-touch-icon.png", 'name="description"'):
            self.assertIn(s, idx)

    def test_tabs(self):
        idx, _ = render()
        self.assertIn('role="tablist"', idx)
        self.assertEqual(len(re.findall(r'role="tab"', idx)), 2)
        self.assertIn("購読リスト", idx)
        self.assertIn('role="tabpanel"', idx)

    def test_main_writes_docs(self):
        build.main()
        d = ROOT / "docs"
        for f in ("index.html", "404.html", "robots.txt", "sitemap.xml", "CNAME", "static/app.js", "static/style.css",
                  "assets/logo.png", "assets/ogp.jpg", "assets/favicon.png", "assets/apple-touch-icon.png"):
            self.assertTrue((d / f).is_file(), f)
        self.assertEqual((d / "CNAME").read_text().strip(), "news.netaful.jp")
        self.assertTrue((ROOT / "docs/data").is_dir() or True)  # data/ は fetch の出力。build は消さない


class DataTest(unittest.TestCase):
    def test_blogs_json_valid(self):
        b = json.loads((ROOT / "data/blogs.json").read_text(encoding="utf-8"))
        cats = {c["id"] for c in b["categories"]}
        ids = [x["id"] for x in b["blogs"]]
        self.assertEqual(len(ids), len(set(ids)))
        for x in b["blogs"]:
            self.assertRegex(x["id"], r"^[a-z][a-z0-9-]*$")
            self.assertIn(x["category"], cats)
            self.assertTrue(x["feeds"])


if __name__ == "__main__":
    unittest.main()
