#!/usr/bin/env python3
"""data/blogs.json の書き方を確かめる。GitHub の Web 画面で編集したあとの打ち間違いを、
取得の前に日本語で知らせるためのもの。問題があれば一覧を出して終了コード1。
実行: python3 scripts/check_blogs.py"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOG_KEYS = {"id", "name", "category", "site_url", "feeds", "include_categories", "exclude_categories", "exclude_urls", "title_suffix", "enabled"}
CAT_KEYS = {"id", "name", "order"}
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://\S+$")


def str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def validate(bundle):
    """問題の説明（日本語）の配列を返す。空なら正常。"""
    errs = []
    if not isinstance(bundle, dict) or not isinstance(bundle.get("categories"), list) \
            or not isinstance(bundle.get("blogs"), list):
        return ["全体は {\"categories\": [...], \"blogs\": [...]} の形にしてください"]
    cat_ids = set()
    for i, c in enumerate(bundle["categories"], 1):
        where = f"categories の{i}件目"
        if not isinstance(c, dict):
            errs.append(f"{where}: {{ }} で囲んだ形にしてください")
            continue
        for k in sorted(set(c) - CAT_KEYS):
            errs.append(f"{where}: 知らない項目「{k}」（書き間違いでは？）")
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.match(cid):
            errs.append(f"{where}: id は英小文字・数字・ハイフンで書いてください（いま: {cid!r}）")
        elif cid in cat_ids:
            errs.append(f"{where}: id「{cid}」が重複しています")
        else:
            cat_ids.add(cid)
        if not isinstance(c.get("name"), str) or not c.get("name", "").strip():
            errs.append(f"{where}: name（表示名）がありません")
        if not isinstance(c.get("order"), int) or isinstance(c.get("order"), bool):
            errs.append(f"{where}: order は数字で書いてください（引用符なし）")
    ids = set()
    for i, b in enumerate(bundle["blogs"], 1):
        where = f"blogs の{i}件目"
        if not isinstance(b, dict):
            errs.append(f"{where}: {{ }} で囲んだ形にしてください")
            continue
        if isinstance(b.get("name"), str):
            where += f"（{b['name']}）"
        for k in sorted(set(b) - BLOG_KEYS):
            errs.append(f"{where}: 知らない項目「{k}」（書き間違いでは？）")
        bid = b.get("id")
        if not isinstance(bid, str) or not ID_RE.match(bid):
            errs.append(f"{where}: id は英小文字・数字・ハイフンで書いてください（いま: {bid!r}）")
        elif bid in ids:
            errs.append(f"{where}: id「{bid}」が重複しています")
        else:
            ids.add(bid)
        if not isinstance(b.get("name"), str) or not b.get("name", "").strip():
            errs.append(f"{where}: name（表示名）がありません")
        if b.get("category") not in cat_ids:
            errs.append(f"{where}: category「{b.get('category')}」は categories にありません")
        if not isinstance(b.get("site_url"), str) or not URL_RE.match(b.get("site_url", "")):
            errs.append(f"{where}: site_url は https:// で始まるURLにしてください")
        feeds = b.get("feeds")
        if not str_list(feeds) or not feeds or not all(URL_RE.match(f) for f in feeds):
            errs.append(f"{where}: feeds は [\"https://...\"] の形で1本以上書いてください")
        for k in ("include_categories", "exclude_categories", "exclude_urls"):
            if k in b and not (b[k] == [] or str_list(b[k])):
                errs.append(f"{where}: {k} は [\"語\", \"語\"] の形にしてください（空なら []）")
        if "title_suffix" in b and not (isinstance(b["title_suffix"], str) and b["title_suffix"].strip()):
            errs.append(f"{where}: title_suffix は落としたい文字列を \"…\" で書いてください")
        if "enabled" in b and not isinstance(b["enabled"], bool):
            errs.append(f"{where}: enabled は true か false（引用符なし）にしてください")
    return errs


def load(path):
    """(bundle, errors)。JSON として読めなければ行・列つきの説明を返す。"""
    text = Path(path).read_text(encoding="utf-8")
    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as e:
        hint = "直前の行の末尾のカンマ（,）の付け忘れ・付けすぎ、引用符（\"）の閉じ忘れが多いです"
        return None, [f"JSONとして読めません: {e.lineno}行目 {e.colno}文字目付近（{e.msg}）。{hint}"]
    return bundle, validate(bundle)


def main():
    _, errs = load(ROOT / "data/blogs.json")
    if errs:
        print("data/blogs.json に直すところがあります:")
        for e in errs:
            print("- " + e)
        return 1
    print("data/blogs.json は正常です")
    return 0


if __name__ == "__main__":
    sys.exit(main())
