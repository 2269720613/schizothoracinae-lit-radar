#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精选→精读 集成管线

流程：
  1. 读取当日精选论文（.state.json + data.json）
  2. 对每篇调用 acquire_pdf 自动获取全文（直链/PMC XML/浏览器队列）
  3. 对已获取 PDF 的论文，调用 DeepPaperNote run_pipeline.py 完成确定性阶段
  4. 输出状态报告：已就绪 / 需浏览器下载 / 失败

用法：
  python run_deepread.py [--date YYYY-MM-DD] [--dry-run] [--limit N]
  --date     精选日期（默认：最近一次）
  --dry-run  只打印计划，不执行下载和管线
  --limit    最多处理 N 篇
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# ── 路径 ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path("/home/wsl/08_work/schizothoracinae-lit-radar")
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
DEEPREAD_WORK = PROJECT_ROOT / "deepread_work"
STATE_PATH = Path(r"/mnt/d/笔记本/文献阅读/文献阅读/文献精读/文献雷达/.state.json")
DATA_PATH = PROJECT_ROOT / "data" / "data.json"
DEEPPAPERNOTE_PIPELINE = Path("/home/wsl/shared-agent-skills/DeepPaperNote/skills/deeppapernote/scripts/run_pipeline.py")
OBSIDIAN_VAULT = "/mnt/d/笔记本/文献阅读/文献阅读"

# 确保 acquire_pdf 可导入
sys.path.insert(0, str(SCRIPTS_DIR))
import acquire_pdf  # noqa: E402

TRACK_FOLDER = {
    "A": "裂腹鱼亚科",
    "B": "演化生物学",
    "C": "着丝粒生物学",
    "D": "古气候基因组学",
}


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pushed": {}}


def load_data():
    if DATA_PATH.exists():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def make_slug(p, year):
    """生成文件名 slug"""
    import re
    first = ""
    authors = p.get("authors") or []
    if authors:
        a = authors[0] if isinstance(authors[0], str) else authors[0].get("name", "")
        first = re.sub(r"[^A-Za-z]", "", a)[:8]
    title = (p.get("title") or "").lower()
    words = re.findall(r"[a-z0-9]+", title)
    stop = {"a", "an", "the", "of", "and", "in", "on", "for", "to", "with", "from", "by", "at"}
    keep = [w for w in words if w not in stop][:4]
    short = "_".join(keep) if keep else "paper"
    return f"{first}{year}_{short}"


def get_selected_papers(date_str):
    """获取指定日期的精选论文列表"""
    state = load_state()
    pushed = state.get("pushed", {})
    if date_str not in pushed:
        print(f"ERROR: {date_str} 无精选记录")
        return []
    ids = pushed[date_str]
    data = load_data()
    if not data:
        print("ERROR: 无法加载 data.json")
        return []

    papers = []
    for tid in ("A", "B", "C", "D"):
        track = data.get("tracks", {}).get(tid)
        if not track:
            continue
        for p in track.get("papers", []):
            pid = p.get("id") or (p.get("doi") or "")
            if pid in ids:
                p["_track"] = tid
                p["_slug"] = make_slug(p, (p.get("date") or date_str)[:4])
                papers.append(p)
    # 去重
    seen = set()
    unique = []
    for p in papers:
        pid = p.get("id") or p.get("doi") or p.get("title")
        if pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique


def run_deeppapernote_pipeline(pdf_path, slug, subdir=None):
    """调用 DeepPaperNote 确定性阶段管线"""
    workdir = DEEPREAD_WORK / f"{slug}_pdfs"
    workdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(DEEPPAPERNOTE_PIPELINE),
        "--input", str(pdf_path),
        "--workdir", str(DEEPREAD_WORK),
        "--prefix", slug,
        "--language", "zh-CN",
        "--save-mode", "obsidian",
        "--vault", OBSIDIAN_VAULT,
    ]
    if subdir:
        cmd.extend(["--papers-dir", subdir])
    print(f"  运行 DeepPaperNote 管线: {' '.join(cmd)}", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
        if result.returncode == 0:
            print(f"  [pipeline] OK: {slug}", flush=True)
            return True
        else:
            print(f"  [pipeline] FAILED: {slug}", flush=True)
            print(f"  stderr: {result.stderr[-500:]}", flush=True)
            return False
    except subprocess.TimeoutExpired:
        print(f"  [pipeline] TIMEOUT: {slug}", flush=True)
        return False
    except Exception as e:
        print(f"  [pipeline] ERROR: {e}", flush=True)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="", help="精选日期 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 篇（0=全部）")
    args = ap.parse_args()

    state = load_state()
    pushed = state.get("pushed", {})
    date_str = args.date or max(pushed.keys(), default="")
    if not date_str:
        print("ERROR: 无精选记录")
        return 1

    papers = get_selected_papers(date_str)
    if not papers:
        print(f"ERROR: {date_str} 无精选论文")
        return 1

    if args.limit > 0:
        papers = papers[: args.limit]

    print(f"=== {date_str} 精选 {len(papers)} 篇，开始获取全文 ===", flush=True)

    results = {"ready": [], "need_browser": [], "failed": [], "pmc_xml": []}

    for i, p in enumerate(papers, 1):
        slug = p.get("_slug", "paper")
        title = (p.get("title") or "")[:70]
        tid = p.get("_track", "?")
        print(f"\n[{i}/{len(papers)}] [{tid}] {slug}", flush=True)
        print(f"  {title}", flush=True)

        if args.dry_run:
            print(f"  (dry-run) doi={p.get('doi','')} pmcid={p.get('pmcid','')} pdf_url={bool(p.get('pdf_url'))}", flush=True)
            continue

        # 调用 acquire_pdf
        paper_input = {
            "doi": p.get("doi", ""),
            "pmcid": p.get("pmcid", ""),
            "pdf_url": p.get("pdf_url", ""),
            "url": p.get("url", ""),
            "slug": slug,
            "title": p.get("title", ""),
        }
        result = acquire_pdf.acquire(paper_input)
        result["slug"] = slug
        result["title"] = title
        result["track"] = tid

        if result["status"] == "ok":
            path = result["path"]
            if path.endswith(".xml"):
                results["pmc_xml"].append(result)
                print(f"  → PMC XML 已获取: {path}", flush=True)
            else:
                results["ready"].append(result)
                print(f"  → PDF 已就绪: {path}", flush=True)
                # 自动运行 DeepPaperNote 确定性阶段
                subdir = TRACK_FOLDER.get(tid)
                run_deeppapernote_pipeline(path, slug, subdir)
        elif result["status"] == "need_browser":
            results["need_browser"].append(result)
            print(f"  → 需浏览器下载: {result['browser_url']}", flush=True)
        else:
            results["failed"].append(result)
            print(f"  → 获取失败: {result.get('reason','')}", flush=True)

        time.sleep(0.5)

    # 输出汇总
    print(f"\n{'='*60}", flush=True)
    print(f"处理完成: {date_str}", flush=True)
    print(f"  PDF 已就绪 + 管线运行: {len(results['ready'])}", flush=True)
    print(f"  PMC XML 已获取: {len(results['pmc_xml'])}", flush=True)
    print(f"  需浏览器下载: {len(results['need_browser'])}", flush=True)
    print(f"  获取失败: {len(results['failed'])}", flush=True)

    if results["need_browser"]:
        print(f"\n浏览器下载队列: {acquire_pdf.BROWSER_QUEUE}", flush=True)
        for r in results["need_browser"]:
            print(f"  - {r['slug']}: {r['browser_url']}", flush=True)

    # 保存结果
    report_path = DEEPREAD_WORK / f"deepread_report_{date_str}.json"
    DEEPREAD_WORK.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已保存: {report_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
