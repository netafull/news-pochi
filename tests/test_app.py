"""static/app.js の純粋関数の検証。macOS の osascript(JXA) で実行する（node 不要）。
osascript が無い環境ではスキップする。"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "static/app.js"

RUNNER = r"""
ObjC.import('Foundation');
function readFile(p){ return ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError($(p), $.NSUTF8StringEncoding, null)); }
var args = $.NSProcessInfo.processInfo.arguments;
var jsPath = ObjC.unwrap(args.objectAtIndex(args.count - 2));
var casePath = ObjC.unwrap(args.objectAtIndex(args.count - 1));
var N = eval(readFile(jsPath) + ";NewsPochi");
var C = JSON.parse(readFile(casePath));
var out = {
  enc: C.subs.map(function (s) { return N.encodeSpell(s); }),
  dec: C.spells.map(function (t) { return N.decodeSpell(t, C.known); }),
  b64: C.strs.map(function (s) { return [N.b64urlEncode(s), N.b64urlDecode(N.b64urlEncode(s))]; }),
  active: N.activeIds(C.sub, C.known),
  toggled: N.toggle(C.sub, C.tid, C.known),
  filtered: N.filterArticles(C.articles, C.active, C.category, C.cat).map(function (a) { return a.url; }),
  fmt: C.dates.map(function (d) { return N.fmtJst(d); }),
  cookie: N.readCookie(C.cookie, 'np_sub'),
  http: C.urls.map(function (u) { return N.isHttp(u); })
};
JSON.stringify(out);
"""


@unittest.skipUnless(shutil.which("osascript"), "osascript が無いのでJSのロジックは未検証")
class AppLogicTest(unittest.TestCase):
    def run_case(self, **kw):
        base = {"subs": [], "spells": [], "known": ["a", "b", "c"], "strs": [], "sub": {"mode": "all"}, "tid": "a",
                "articles": [], "active": [], "category": "", "cat": {}, "dates": [], "cookie": "", "urls": []}
        base.update(kw)
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "runner.js").write_text(RUNNER, encoding="utf-8")
            (t / "case.json").write_text(json.dumps(base), encoding="utf-8")
            r = subprocess.run(["osascript", "-l", "JavaScript", str(t / "runner.js"), str(JS), str(t / "case.json")],
                               capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout.strip())

    def test_js_loads(self):
        self.run_case()  # 構文エラーがあればここで落ちる

    def test_encode(self):
        import base64
        r = self.run_case(subs=[{"mode": "all"}, {"mode": "custom", "ids": ["gorime", "netaful-eat"]}, {"mode": "custom", "ids": []}])
        want = "np1-" + base64.urlsafe_b64encode(b"gorime,netaful-eat").decode().rstrip("=")
        self.assertEqual(r["enc"], ["np1-all", want, "np1-"])

    def test_decode(self):
        import base64
        e = lambda s: "np1-" + base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
        r = self.run_case(spells=["np1-all", e("a,c"), e("a,zzz,b,a"), e(""), "np1-", "xx-all", "np2-all", "np1-!!!", "np1-a", "  np1-all \n", "", e("a,b")[:-3]])
        d = r["dec"]
        self.assertEqual(d[0], {"mode": "all"})
        self.assertEqual(d[1], {"mode": "custom", "ids": ["a", "c"]})
        self.assertEqual(d[2], {"mode": "custom", "ids": ["a", "b"]})  # 未知idは黙って捨て、重複も除く
        self.assertEqual(d[3], {"mode": "custom", "ids": []})
        self.assertEqual(d[4], {"mode": "custom", "ids": []})
        self.assertIsNone(d[5])
        self.assertIsNone(d[6])
        self.assertIsNone(d[7])
        self.assertIsNone(d[8])  # 長さが不正な base64
        self.assertEqual(d[9], {"mode": "all"})
        self.assertIsNone(d[10])

    def test_b64_roundtrip_and_matches_python(self):
        import base64
        strs = ["", "a", "ab", "abc", "abcd", "a,b,c", "日本語,id", "emoji\U0001F363"]
        for s, (enc, dec) in zip(strs, self.run_case(strs=strs)["b64"]):
            self.assertEqual(enc, base64.urlsafe_b64encode(s.encode()).decode().rstrip("="), s)
            self.assertEqual(dec, s)

    def test_active_and_toggle(self):
        self.assertEqual(self.run_case(sub={"mode": "all"})["active"], ["a", "b", "c"])
        self.assertEqual(self.run_case(sub={"mode": "custom", "ids": ["c", "a"]})["active"], ["a", "c"])
        # 全部モードで1つ触るとカスタムに移り、その時点のオン一覧（触った分を除く）を保存する
        self.assertEqual(self.run_case(sub={"mode": "all"}, tid="b")["toggled"], {"mode": "custom", "ids": ["a", "c"]})
        # カスタムではオフのものを入れる（新規ブログは自動では入らない）
        self.assertEqual(self.run_case(sub={"mode": "custom", "ids": ["a"]}, tid="c")["toggled"], {"mode": "custom", "ids": ["a", "c"]})
        self.assertEqual(self.run_case(sub={"mode": "custom", "ids": ["a"]}, tid="a")["toggled"], {"mode": "custom", "ids": []})

    def test_filter(self):
        arts = [{"url": "https://x/1", "title": "t", "blog": "a"}, {"url": "https://x/2", "title": "t", "blog": "b"},
                {"url": "javascript:1", "title": "t", "blog": "a"}, {"url": "https://x/3", "title": "", "blog": "a"},
                {"url": "https://x/4", "title": "t", "blog": "c"}]
        cat = {"a": "apple", "b": "food", "c": "apple"}
        self.assertEqual(self.run_case(articles=arts, active=["a", "b"], cat=cat)["filtered"], ["https://x/1", "https://x/2"])
        self.assertEqual(self.run_case(articles=arts, active=["a", "b", "c"], category="apple", cat=cat)["filtered"],
                         ["https://x/1", "https://x/4"])
        self.assertEqual(self.run_case(articles=arts, active=[], cat=cat)["filtered"], [])

    def test_fmt_jst(self):
        r = self.run_case(dates=["2026-11-24T05:05:00Z", "2026-11-23T15:00:00Z", "2026-12-01T00:00:00+09:00", "bad"])["fmt"]
        self.assertEqual(r, ["11/24 14:05", "11/24 00:00", "12/1 00:00", ""])

    def test_cookie_and_http(self):
        self.assertEqual(self.run_case(cookie="a=1; np_sub=np1-all; b=2")["cookie"], "np1-all")
        self.assertIsNone(self.run_case(cookie="xnp_sub=1")["cookie"])
        self.assertEqual(self.run_case(urls=["https://a", "http://a", "javascript:1", "//a", None, 5])["http"],
                         [True, True, False, False, False, False])


if __name__ == "__main__":
    unittest.main()
