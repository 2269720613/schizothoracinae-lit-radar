#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Obsidian 文献雷达日报生成器
每日从裂腹鱼/演化基因组学文献雷达拉取最新 data.json,
按四个领域轨精选"最值得推进"的文献, 生成 Obsidian 日记。

数据源优先级:
  1) GitHub raw (公开仓库, 始终最新)
  2) 本地 repo data/data.json (\\wsl.localhost\\... UNC, 兜底)

产出:
  D:\\笔记本\\文献阅读\\文献阅读\\文献精读\\文献雷达\\YYYY-MM-DD.md
去重状态:
  <repo>/data/obsidian_pushed.json  (记录已推送论文 id, 避免跨日重复)

用法(Windows):
  python scripts/obsidian_digest.py [--days N] [--top N] [--dry-run]
"""
import argparse
import json
import socket
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

socket.setdefaulttimeout(25)

# ---- 常量 ----
RAW_URL = "https://raw.githubusercontent.com/2269720613/schizothoracinae-lit-radar/main/data/data.json"
LOCAL_DATA = Path(r"\\wsl.localhost\CJJ\home\wsl\08_work\schizothoracinae-lit-radar\data\data.json")
STATE_PATH = Path(r"D:\笔记本\文献阅读\文献阅读\文献精读\文献雷达\.state.json")
VAULT_DIR = Path(r"D:\笔记本\文献阅读\文献阅读\文献精读\文献雷达")

TRACK_LABELS = {
    "A": "裂腹鱼亚科物种精确检索",
    "B": "生物生信演化分析",
    "C": "着丝粒研究",
    "D": "古地理古气候与基因组演化",
}

# 相关性关键词: 命中越多的论文越"值得推进" (反映本项目研究主线)
RELEVANCE = {
    "A": ["schizothorax", "schizothoracinae", "gymnocypris", "schizopygopsis",
          "ptychobarbus", "diptychus", "haplotype", "genome", "polyploid",
          "tibetan", "qinghai", "plateau", "karyotype", "adaptation"],
    "B": ["polyploid", "rediploidization", "allopolyploid", "autopolyploid",
          "introgression", "gene flow", "d-statistic", "abba-baba", "phylogenom",
          "population genomics", "high-altitude", "adaptation", "selection",
          "cyprinid", "teleost", "hi-c", "phasing", "diploidiz", "subgenome"],
    "C": ["centromere", "cenp", "kinetochore", "satellite dna", "satellitome",
          "holocentromere", "centromeric", "hi-c", "neocentromere", "alpha satellite",
          "monomeric", "repeat", "chromosome", "transposable", "cryptic"],
    "D": ["paleoclimate", "paleodrainage", "quaternary", "pleistocene",
          "phylogeography", "tectonic", "uplift", "tibetan plateau", "climate change",
          "glacial", "refugia", "drainage", "gansu", "qinghai", "rangewide",
          "demographic", "range dynamics", "biogeography"],
}

EXCLUDE = ["stress", "tolerance", "acclimat", "heat shock", "cortisol", "antioxidant"]


# 数据源顺序: jsdelivr 多 CDN 前端(国内一般可达)优先, github-raw 兜底
DATA_SOURCES = [
    ("jsdelivr-cdn", "https://cdn.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("jsdelivr-fastly", "https://fastly.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("jsdelivr-gcore", "https://gcore.jsdelivr.net/gh/2269720613/schizothoracinae-lit-radar@main/data/data.json"),
    ("github-raw", "https://raw.githubusercontent.com/2269720613/schizothoracinae-lit-radar/main/data/data.json"),
]


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "lit-radar-obsidian/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def _load_data_impl():
    """实际拉取逻辑(在守护线程中执行, 由硬超时兜底)。"""
    for name, url in DATA_SOURCES:
        for attempt in range(2):
            try:
                d = json.loads(http_get(url))
                if d:
                    return d, name
            except Exception as exc:
                print(f"WARN: {name} 第{attempt+1}次失败: {exc}", file=sys.stderr)
    # 有界本地回退: 读仓库本地 data.json (可能略旧, 但去重逻辑保证不会重复推送)。
    try:
        if LOCAL_DATA.exists():
            return json.loads(LOCAL_DATA.read_text(encoding="utf-8")), "local"
    except Exception as exc:
        print(f"WARN: read local data failed: {exc}", file=sys.stderr)
    return None, None


def load_data():
    """带硬总超时的数据拉取: 网络/DNS 挂起时最多等 FETCH_BUDGET 秒。"""
    import threading
    holder = {}

    def _worker():
        holder["r"] = _load_data_impl()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=70)
    if holder.get("r") and holder["r"][0]:
        return holder["r"]
    print("ERROR: 数据拉取超时或所有数据源不可用(70s 硬超时)", file=sys.stderr)
    return None, None


def load_state():
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if "pushed" not in st and st.get("pushed_ids"):
                # 旧结构迁移: 历史已推送记录归档到远古日期, 始终排除
                st["pushed"] = {"2000-01-01": st["pushed_ids"]}
            st.pop("pushed_ids", None)  # 始终丢弃历史遗留键
            return st
        except Exception:
            pass
    return {"pushed": {}, "last_run": "", "last_note": ""}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_fish_paper(p):
    return bool(p.get("is_fish")) or p.get("track") == "A"


def title_contains(p, frags):
    t = (p.get("title") or "").lower()
    return [f for f in frags if f in t]


def score_paper(p, track, now, days):
    """返回 (score, reasons)。score 越高越值得推进。"""
    reasons = []
    tier = p.get("tier")
    if tier in (1,):
        base = 60
        reasons.append("T1 顶刊/一区")
    elif tier in (2,):
        base = 40
        reasons.append("T2 优质(指标达标)")
    elif tier in (3,):
        base = 20
        reasons.append("T3 预印本")
    else:
        return -1, []

    date_str = (p.get("date") or "")[:10]
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            age = (now - d).days
            if age < 0:
                base += 35
                reasons.append("在线优先(即将正式见刊)")
            elif age <= 7:
                base += 30
                reasons.append("7 天内新增")
            elif age <= days:
                base += 15
                reasons.append(f"{age} 天前")
        except ValueError:
            pass

    hits = title_contains(p, RELEVANCE.get(track, []))
    base += 8 * min(len(hits), 4)
    if hits:
        reasons.append("命中核心关注词: " + ", ".join(hits[:3]))

    # 鱼类论文在非 A 轨额外加权(用户主线是裂腹鱼基因组)
    if track != "A" and is_fish_paper(p):
        base += 14
        reasons.append("鱼类研究")

    # 相关性门槛: 未命中任何核心关注词且非鱼类的论文, 大幅降权,
    # 仅当该轨确实没有更贴合主线的论文时才可能补位
    if not hits and not is_fish_paper(p):
        base -= 24
        reasons.append("未命中核心关注词(相关性一般)")
    return base, reasons


def fmt_authors(authors, n=4):
    if not authors:
        return "—"
    if len(authors) <= n:
        return ", ".join(authors)
    return ", ".join(authors[:n]) + " 等"


def make_reason_line(reasons):
    return "; ".join(reasons) if reasons else ""


def render_note(data, picks, now, src):
    today = now.strftime("%Y-%m-%d")
    gen = data.get("generated_at", "")
    stats = data.get("stats", {})
    lines = []
    lines.append("---")
    lines.append("tags:")
    lines.append("  - papers/文献雷达")
    lines.append(f"date: {today}")
    lines.append("来源: 裂腹鱼/演化基因组学文献雷达 (GitHub Actions 每日抓取)")
    lines.append("---")
    lines.append("")
    lines.append(f"# 文献雷达日报 · {today}")
    lines.append("")
    lines.append(f"> 数据快照：共 {stats.get('total_count', '?')} 篇 ｜ 本周新增 {stats.get('new_this_week', '?')} ｜ 数据更新时间 {gen} ｜ 数据源 {src}")
    lines.append("")
    lines.append("> 筛选口径：按 期刊层级(T1→T2→T3) + 时效(7天内/窗口内) + 与项目主线相关性 综合打分，每轨精选 Top 若干；已推送过的论文不再重复推送。")
    lines.append("")
    total_picked = 0
    for tid in ("A", "B", "C", "D"):
        label = TRACK_LABELS.get(tid, tid)
        tpicks = picks.get(tid, [])
        lines.append(f"## {tid} · {label}（精选 {len(tpicks)} 篇）")
        lines.append("")
        if not tpicks:
            lines.append("今日无新增符合条件的精选。")
            lines.append("")
            continue
        for i, p in enumerate(tpicks, 1):
            total_picked += 1
            title = (p.get("title") or "无标题").strip()
            journal = p.get("journal") or "—"
            date_s = (p.get("date") or "")[:10]
            doi = p.get("doi") or ""
            url = p.get("url") or ("https://doi.org/" + doi if doi else "")
            tier = p.get("tier")
            tier_tag = {1: "T1·顶刊/一区", 2: "T2·优质", 3: "T3·预印本"}.get(tier, str(tier))
            src_badge = p.get("source", "")
            lines.append(f"### {i}. {title}")
            lines.append("")
            lines.append(f"- **期刊 / 层级**：{journal} ｜ {tier_tag} ｜ {src_badge}")
            lines.append(f"- **发表**：{date_s}")
            lines.append(f"- **作者**：{fmt_authors(p.get('authors') or [])}")
            if doi:
                lines.append(f"- **DOI**：{doi}")
            if url:
                lines.append(f"- **链接**：[打开论文]({url})")
            lines.append(f"- **为什么值得推进**：{p.get('_reason') or '—'}")
            abstract = (p.get("abstract") or "").strip()
            if abstract:
                if len(abstract) > 400:
                    abstract = abstract[:400] + "…"
                lines.append(f"- **摘要**：{abstract}")
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("> 本日报由文献雷达每日自动生成；想看某篇的深度精读可随时让我展开。")
    lines.append("")
    return "\n".join(lines), total_picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="初选时间窗口(天)")
    ap.add_argument("--top", type=int, default=5, help="每轨精选篇数上限")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    ap.add_argument("--reset", action="store_true", help="清空已推送记录后重新精选")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    print(f"[{now:%Y-%m-%d %H:%M:%S}] 拉取雷达数据 ...", flush=True)
    data, src = load_data()
    if not data:
        print("ERROR: 无法获取雷达数据(网络与本地均失败)")
        return 1
    stats_all = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
    print(f"[{now:%Y-%m-%d %H:%M:%S}] 数据源={src}, 总文献数={stats_all.get('total_count')}", flush=True)

    state = load_state()
    if args.reset:
        state["pushed"] = {}
        state.pop("pushed_ids", None)
    today = now.strftime("%Y-%m-%d")
    pushed_by_date = state.get("pushed", {})
    previous_ids = set()
    for d, ids in pushed_by_date.items():
        if d != today:
            previous_ids.update(ids)
    today_ids = set(pushed_by_date.get(today, []))
    cutoff = (now - timedelta(days=args.days)).date().isoformat()

    # id -> [(tid, paper)] 索引(同一论文可能出现在多个轨)
    index = {}
    for tid in ("A", "B", "C", "D"):
        track = data.get("tracks", {}).get(tid)
        if not track:
            continue
        for p in track.get("papers", []):
            pid = p.get("id") or (p.get("doi") or "")
            if pid:
                index.setdefault(pid, []).append((tid, p))

    picks = {}
    for tid in ("A", "B", "C", "D"):
        track = data.get("tracks", {}).get(tid)
        if not track:
            picks[tid] = []
            continue
        scored = []
        for p in track.get("papers", []):
            pid = p.get("id") or (p.get("doi") or "")
            if not pid or pid in previous_ids:
                continue
            d = (p.get("date") or "")[:10]
            if d < cutoff:
                continue
            t = (p.get("title") or "").lower()
            if any(x in t for x in EXCLUDE):
                continue
            s, reasons = score_paper(p, tid, now, args.days)
            if s < 0:
                continue
            scored.append((s, p, reasons))
        scored.sort(key=lambda x: (-x[0], x[1].get("date", "")))
        top = scored[: args.top]
        for s, p, reasons in top:
            p["_reason"] = make_reason_line(reasons)
        merged = [p for _, p, _ in top]
        seen = set(p.get("id") or p.get("doi") or "" for p in merged)
        # 并入当天已推送的论文, 保证同日多次运行不丢失
        for pid in sorted(today_ids):
            for tid2, p in index.get(pid, []):
                if tid2 == tid and pid not in seen:
                    if not p.get("_reason"):
                        s2, reasons2 = score_paper(p, tid, now, args.days)
                        p["_reason"] = make_reason_line(reasons2) if s2 > 0 else "今日早前精选(保留)"
                    merged.append(p)
                    seen.add(pid)
        picks[tid] = merged

    note_text, total = render_note(data, picks, now, src)

    if args.dry_run:
        print(note_text)
        print(f"\n[dry-run] 共精选 {total} 篇")
        return 0

    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    out = VAULT_DIR / f"{today}.md"
    out.write_text(note_text, encoding="utf-8")

    note_ids = []
    for tid, plist in picks.items():
        for p in plist:
            pid = p.get("id") or (p.get("doi") or "")
            if pid:
                note_ids.append(pid)
    pushed_by_date[today] = sorted(set(today_ids) | set(note_ids))
    state["pushed"] = pushed_by_date
    state["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state["last_note"] = str(out)
    save_state(state)

    all_pushed = set()
    for ids in pushed_by_date.values():
        all_pushed.update(ids)
    print(f"OK: 生成 {out} (今日精选 {total} 篇, 累计已推送 {len(all_pushed)} 篇)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())