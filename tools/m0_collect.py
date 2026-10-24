#!/usr/bin/env python3
"""
M0 · Q3 语料采集器

从公开网页抓取中文小说章节，抽取正文段落，存成语料文件并登记来源。

⚠️ 版权说明
----------
抓取的内容**仅用于内部统计标定**（测量文本多样性指标的参考区间），
不提交到仓库（默认输出目录在 .gitignore 里），不用于训练、不对外分发。
`--out` 指向仓库内时请确认该路径已被忽略。

用法
----
    python tools/m0_collect.py --url "https://..." --out m0_corpus --name 001
    python tools/m0_collect.py --url-file urls.txt --out m0_corpus
    python tools/m0_collect.py --url "https://..." --out m0_corpus --print   # 看抽取结果

抽取策略
--------
1. 用浏览器 UA 抓取，按响应头 / 页面 meta 猜编码（中文站多为 GBK）
2. 去掉 script / style / 注释 / 标签
3. 把连续的"中文 + 中文标点 + 空白"块切出来，取**最长的那块**作为正文
4. 截取前 --chars 个字符（默认 2000，落在 800~3000 的有效区间）
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.request
from pathlib import Path

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_DROP = re.compile(r"(?is)<(script|style|noscript|iframe|svg)[^>]*>.*?</\1>")
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_TAG = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")

# 一段"像正文"的最小单位：中文/中文标点/英文数字，允许换行
_TEXTBLOCK = re.compile(r"[一-鿿　-〿＀-￯"
                        r"a-zA-Z0-9\s，。！？；：、""''（）《》「」【】…—·\-]{80,}")


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "gb18030", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text(html: str) -> str:
    html = _COMMENT.sub(" ", html)
    html = _DROP.sub(" ", html)
    html = _TAG.sub("\n", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = _WS.sub(" ", html)

    blocks = _TEXTBLOCK.findall(html)
    if not blocks:
        return ""
    # 取最长的块，再按段落挑出够长的连续段
    best = max(blocks, key=len)
    paras = [p.strip() for p in re.split(r"\n+", best) if len(p.strip()) >= 25]
    if not paras:
        return best.strip()
    return "\n\n".join(paras)


def discover_chapter_links(index_html: str, base_url: str, limit: int = 40) -> list[str]:
    """
    从目录页里找出章节链接。

    优先匹配常见的"章节"链接特征（/chapter/、/chapterid/、/n/、_数字.html 等），
    找不到时退而求其次，取页面里所有 http(s) 链接中形如正文的。
    """
    from urllib.parse import urljoin

    hrefs = re.findall(r'(?i)href=["\']?([^"\'>\s]+)', index_html)
    out: list[str] = []
    seen: set[str] = set()
    chapter_hint = re.compile(r"(?i)(chapter|/\d+[_\-]?\d*\.html|/n/\d+|_chapter)")
    for h in hrefs:
        if h.startswith(("javascript:", "mailto:", "#")):
            continue
        full = urljoin(base_url, h)
        if full in seen:
            continue
        seen.add(full)
        if chapter_hint.search(h) and re.search(r"\d", h):
            out.append(full)
    if not out:
        for h in hrefs:
            if h.startswith(("javascript:", "mailto:", "#")):
                continue
            full = urljoin(base_url, h)
            if full in seen:
                continue
            seen.add(full)
            if re.search(r"\.(html?|shtml)$", h) and re.search(r"\d{3,}", h):
                out.append(full)
    return out[:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="M0 Q3 语料采集")
    ap.add_argument("--url", action="append", default=[], help="可重复")
    ap.add_argument("--url-file", type=Path, default=None, help="每行一个 URL")
    ap.add_argument("--index", action="append", default=[],
                    help="目录页 URL：自动发现其中的章节链接并逐章抓取（可重复）")
    ap.add_argument("--max-per-index", type=int, default=8, help="每个目录页最多抓几章")
    ap.add_argument("--out", type=Path, default=Path("m0_corpus"))
    ap.add_argument("--chars", type=int, default=2000)
    ap.add_argument("--min-chars", type=int, default=800)
    ap.add_argument("--name", default="", help="单 URL 时的文件名（不含扩展名）")
    ap.add_argument("--print", dest="show", action="store_true", help="打印抽取结果")
    ap.add_argument("--delay", type=float, default=1.5, help="请求间隔秒数")
    args = ap.parse_args()

    urls = list(args.url)
    if args.url_file and args.url_file.exists():
        urls += [ln.strip() for ln in args.url_file.read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]

    for idx_url in args.index:
        try:
            html = decode(fetch(idx_url))
        except Exception as e:
            print(f"  [目录页抓取失败] {idx_url} -> {type(e).__name__}")
            continue
        links = discover_chapter_links(html, idx_url, limit=args.max_per_index * 4)
        print(f"  [目录页] {idx_url[:70]} → 发现 {len(links)} 个章节链接")
        urls += links[: args.max_per_index]

    if not urls:
        print("没有 URL。用 --url 或 --url-file 提供。")
        return 1

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    src_path = out / "sources.csv"
    known = set()
    if src_path.exists():
        with src_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if row:
                    known.add(row[0])

    n_new = n_skip = 0
    for i, url in enumerate(urls, start=1):
        try:
            text = extract_text(decode(fetch(url)))
        except Exception as e:
            print(f"  [抓取失败] {url} -> {type(e).__name__}")
            continue

        if len(text) < args.min_chars:
            print(f"  [太短 {len(text):>5}] {url[:80]}")
            n_skip += 1
            continue

        name = args.name if (args.name and len(urls) == 1) else f"pass_{i:03d}"
        fname = f"{name}.txt"
        if fname in known:
            n_skip += 1
            continue
        (out / fname).write_text(text[: args.chars], encoding="utf-8")

        with src_path.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow([fname, url, len(text[: args.chars]), time.strftime("%Y-%m-%d")])
        print(f"  [OK] {fname}  {len(text[: args.chars])} 字  {url[:70]}")
        n_new += 1
        if args.show:
            print("      " + text[: args.chars][:400].replace("\n", " ") + " …")
        time.sleep(args.delay)

    print(f"\n新增 {n_new} 段，跳过 {n_skip} 段 → {out}")
    print("下一步：人工标注 AI 味档位，写入 labels.csv（见 docs/M0/03-语料采集与标注.md）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
