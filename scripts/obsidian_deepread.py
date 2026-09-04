#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Obsidian 精读笔记生成器(摘要级)
读取文献雷达每日精选, 按领域映射到 Obsidian 精读主题目录,
为每篇生成 DeepPaperNote 风格的精读笔记骨架(元数据+摘要+待精读结构)。
合成字段(一句话总结/研究问题/创新点/方法/结果/意义/局限)由 AI 精读时填充。

用法(Windows):
  python scripts/obsidian_deepread.py [--date YYYY-MM-DD] [--scaffold] [--dry-run]
  --date     精选日期(默认: 状态文件最近一次生成日报的日期)
  --scaffold 为当日精选生成骨架笔记(核心信息+全文摘要+待精读结构)
  --dry-run  只打印当日精选清单与映射, 不写文件
"""
import argparse
import json
import re
import socket
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

socket.setdefaulttimeout(25)

# ---- 路径 ----
STATE_PATH = Path(r"D:\笔记本\文献阅读\文献阅读\文献精读\文献雷达\.state.json")
NOTE_ROOT = Path(r"D:\笔记本\文献阅读\文献阅读\文献精读")

# ---- 领域 -> Obsidian 主题目录 ----
TRACK_FOLDER = {
    "A": "裂腹鱼亚科",
    "B": "演化生物学",
    "C": "着丝粒生物学",
    "D": "古气候基因组学",
}
TRACK_LABELS = {
    "A": "裂腹鱼亚科物种精确检索",
    "B": "生物/生信演化分析",
    "C": "着丝粒研究",
    "D": "古地理古气候与基因组演化",
}

# 数据源顺序: jsdelivr 多 CDN 前端优先, github-raw 兜底
DATA_SOURCES = [
    ("jsdelivr-cdn", "https://cdn.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("jsdelivr-fastly", "https://fastly.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("jsdelivr-gcore", "https://gcore.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("github-raw", "https://raw.githubusercontent.com/2269720613/schizothoracinae-lit-radar/main/data/data.json"),
]


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "lit-radar-deepread/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def load_data():
    import threading
    holder = {}

    def _worker():
        for name, url in DATA_SOURCES:
            for attempt in range(2):
                try:
                    d = json.loads(http_get(url))
                    if d:
                        holder["r"] = (d, name)
                        return
                except Exception as exc:
                    print(f"WARN: {name} 第{attempt+1}次失败: {exc}", file=sys.stderr)
        holder["r"] = (None, None)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=70)
    return holder.get("r", (None, None))


def load_state():
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if "pushed" in st:
                return st
        except Exception:
            pass
    return {"pushed": {}}


def fmt_authors(authors, n=6):
    if not authors:
        return "—"
    if len(authors) <= n:
        return ", ".join(authors)
    return ", ".join(authors[:n]) + " 等"


def make_slug(p, year):
    """按 作者年份_短标题 生成 slug, 贴近库内已有命名。"""
    first = ""
    if p.get("authors"):
        a = p["authors"][0]
        first = re.sub(r"[^A-Za-z]", "", a)[:8]
    title = (p.get("title") or "").lower()
    words = re.findall(r"[a-z0-9]+", title)
    keep = []
    for w in words:
        if w in ("a", "an", "the", "of", "and", "in", "on", "for", "to", "with", "from", "by"):
            continue
        keep.append(w)
        if len(keep) >= 4:
            break
    short = "_".join(keep) if keep else "paper"
    return f"{first}{year}_{short}"


def build_note(p, tid, date_str):
    title = (p.get("title") or "").strip()
    doi = p.get("doi") or ""
    url = p.get("url") or (f"https://doi.org/{doi}" if doi else "")
    journal = p.get("journal") or "—"
    authors = p.get("authors") or []
    tier = p.get("tier")
    tier_tag = {1: "T1·顶刊/一区", 2: "T2·优质", 3: "T3·预印本"}.get(tier, str(tier))
    folder = TRACK_FOLDER.get(tid, "文献雷达")
    abstract = (p.get("abstract") or "").strip()
    lines = []
    lines.append("---")
    lines.append("tags:")
    lines.append(f"  - papers/{folder}")
    lines.append(f"date: {date_str}")
    if doi:
        lines.append(f"doi: {doi}")
    lines.append("精读级别: 摘要级精读（待 AI 深度精读填充合成部分）")
    lines.append("---")
    lines.append("")
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## 核心信息")
    lines.append("")
    lines.append(f"- 标题：{title}")
    lines.append(f"- 作者：{fmt_authors(authors)}")
    lines.append(f"- 发表渠道：{journal}（{tier_tag}）")
    lines.append(f"- 领域轨：{tid} {TRACK_LABELS.get(tid, '')}")
    if doi:
        lines.append(f"- DOI：{doi}")
    if url:
        lines.append(f"- 论文链接：{url}")
    lines.append(f"- 精选理由：{p.get('_reason') or '—'}")
    lines.append("")
    lines.append("## 一句话总结")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 研究问题")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 创新点")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 方法与数据")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 关键结果")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 原文摘要")
    lines.append("")
    if abstract:
        lines.append("> " + abstract.replace("\n", " "))
    else:
        lines.append("（该文献数据源未提供摘要，需从 PubMed/OpenAlex 或全文补充）")
    lines.append("")
    lines.append("## 对本项目/领域意义")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 局限与待深入")
    lines.append("")
    lines.append("（待精读填充）")
    lines.append("")
    lines.append("## 引用与链接")
    lines.append("")
    lines.append(f"- 数据来源：文献雷达 data.json（文献雷达精选 {date_str}）")
    if url:
        lines.append(f"- 论文原文：{url}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="精选日期 YYYY-MM-DD(默认取状态最近日报)")
    ap.add_argument("--scaffold", action="store_true", help="生成骨架笔记文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印精选清单")
    args = ap.parse_args()

    state = load_state()
    pushed = state.get("pushed", {})
    if args.date:
        date_str = args.date
    else:
        date_str = max(pushed.keys(), default="")
    if not date_str or not pushed.get(date_str):
        print("ERROR: 没有可用的精选日期(状态为空或指定日期无推送)")
        return 1
    ids = pushed[date_str]
    if not ids:
        print(f"ERROR: {date_str} 无已推送论文")
        return 1

    data, src = load_data()
    if not data:
        print("ERROR: 无法获取雷达数据")
        return 1

    # id -> paper(取出现轨最多优先; 记录出现轨)
    index = {}
    for tid in ("A", "B", "C", "D"):
        track = data.get("tracks", {}).get(tid)
        if not track:
            continue
        for p in track.get("papers", []):
            pid = p.get("id") or (p.get("doi") or "")
            if not pid:
                continue
            if pid in ids:
                rec = index.setdefault(pid, {})
                rec.setdefault("tracks", []).append(tid)
                if "paper" not in rec:
                    rec["paper"] = p
    print(f"[{date_str}] 当日精选 {len(ids)} 篇唯一论文, 数据源 {src}", flush=True)

    written = []
    for pid in sorted(ids):
        rec = index.get(pid)
        if not rec:
            print(f"  ? 未在数据中找到: {pid}")
            continue
        p = rec["paper"]
        tracks = rec["tracks"]
        # 主题目录: 优先取 A->C->B->D 的主轨
        tid = "A" if "A" in tracks else ("C" if "C" in tracks else ("D" if "D" in tracks else "B"))
        year = (p.get("date") or date_str)[:4]
        slug = make_slug(p, year)
        folder = TRACK_FOLDER.get(tid, "文献雷达")
        note_dir = NOTE_ROOT / folder / f"{slug}.zh-CN"
        note_path = note_dir / f"{slug}.zh-CN.md"
        if args.dry_run:
            print(f"  [{tid}] {slug}  ->  {folder}\\{slug}.zh-CN.md")
            print(f"       {(p.get('title') or '').strip()[:90]}")
            print(f"       DOI: {pid}  |  摘要 {len((p.get('abstract') or '').strip())} 字")
            continue
        if note_path.exists():
            print(f"  = 已存在, 跳过: {note_path}")
            continue
        if args.scaffold:
            note_dir.mkdir(parents=True, exist_ok=True)
            note_path.write_text(build_note(p, tid, date_str), encoding="utf-8")
            print(f"  + 骨架: {note_path}")
            written.append(str(note_path))
    if written and not args.dry_run:
        print(f"OK: 生成骨架笔记 {len(written)} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
