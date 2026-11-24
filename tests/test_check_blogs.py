import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_blogs as cb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def ok_bundle():
    return {"categories": [{"id": "apple", "name": "Apple系", "order": 1}],
            "blogs": [{"id": "a-b", "name": "A", "category": "apple", "site_url": "https://a.example/",
                       "feeds": ["https://a.example/feed"], "exclude_categories": [], "enabled": False}]}


class CheckBlogsTest(unittest.TestCase):
    def test_real_file_is_valid(self):
        _, errs = cb.load(ROOT / "data/blogs.json")
        self.assertEqual(errs, [])

    def test_ok(self):
        self.assertEqual(cb.validate(ok_bundle()), [])

    def test_typical_mistakes(self):
        b = ok_bundle()
        blog = b["blogs"][0]
        blog["id"] = "A_B"
        blog["category"] = "food"
        blog["feeds"] = "https://a.example/feed"
        blog["exclude_categry"] = ["x"]
        blog["enabled"] = "false"
        errs = " / ".join(cb.validate(b))
        for word in ("id は英小文字", "category「food」", "feeds は", "知らない項目「exclude_categry」", "enabled は"):
            self.assertIn(word, errs)

    def test_duplicate_id(self):
        b = ok_bundle()
        b["blogs"].append(dict(b["blogs"][0]))
        self.assertTrue(any("重複" in e for e in cb.validate(b)))

    def test_broken_json_reports_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "blogs.json"
            p.write_text('{\n "categories": [],\n "blogs": [\n  {"id": "x"}\n  {"id": "y"}\n ]\n}\n', encoding="utf-8")
            bundle, errs = cb.load(p)
            self.assertIsNone(bundle)
            self.assertIn("5行目", errs[0])
