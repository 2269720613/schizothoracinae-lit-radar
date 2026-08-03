# 裂腹鱼/群体遗传文献雷达 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 搭建一个每日自动刷新的裂腹鱼亚科/群体遗传方法学文献看板,以 Claude Artifact 形式公开发布。

**架构：** GitHub Actions 每日调用 `scripts/fetch.py`(基于 paper-lookup 记录的 OpenAlex/PubMed/bioRxiv REST API 规范做双轨关键词检索)把结果累积写入 `data/data.json` 并 commit;claude.ai 云端 schedule routine 每日拉取最新 `data.json`,跑 `scripts/inject.py` 把数据嵌入 agy 生成的 `template/dashboard.html` 静态模板,再调用 Artifact 工具重新发布到固定 URL。前端模板由本机 `agy` CLI 一次性生成。

**技术栈：** Python 3.12(标准库 `urllib`/`json` + PyYAML),pytest,GitHub Actions,claude.ai RemoteTrigger(schedule routine),Claude Artifact 工具,antigravity CLI(`agy`)。

---

## 文件结构

```
schizothoracinae-lit-radar/
├── README.md                     # 项目说明、本地运行方式、更新链路说明
├── requirements.txt              # PyYAML, pytest
├── pyproject.toml                # pytest pythonpath 配置
├── .gitignore                    # __pycache__/, .pytest_cache/
├── config/
│   └── keywords.yaml             # 双轨关键词配置(可独立于代码调整)
├── scripts/
│   ├── fetch.py                  # 调 OpenAlex/PubMed/bioRxiv API,合并去重写 data/data.json
│   └── inject.py                 # 把 data/data.json 嵌入 template/dashboard.html 生成 dist/dashboard.html
├── tests/
│   ├── test_fetch.py
│   └── test_inject.py
├── template/
│   └── dashboard.html            # agy 一次性生成的静态模板(数据位为占位符 __LIT_RADAR_DATA__)
├── dist/
│   └── dashboard.html            # inject.py 的产出,最终发布给 Artifact 工具的文件
├── data/
│   └── data.json                 # 累积的文献数据(双轨 + 统计)
└── .github/workflows/
    └── fetch.yml                 # 每日 06:00 UTC 定时跑 fetch.py 并 commit
```

- `scripts/fetch.py`:唯一职责是"从外部 API 拉取新文献并合并进现有 data.json",不涉及前端。
- `scripts/inject.py`:唯一职责是"把 data.json 的内容安全嵌入 HTML 模板",不涉及网络请求。
- `template/dashboard.html`:唯一职责是"纯前端展示逻辑",通过约定的占位符字符串与数据层解耦,agy 完全不需要知道数据从哪来。
- 三者之间的接口是文件路径 + 占位符字符串约定,任何一个文件的内部实现都可以独立重写而不影响另外两个。

---

## 任务 0(最高优先级风险验证)：云端 routine 调用 Artifact 工具可行性探针

**说明：** 这是整个架构的关键分叉点。在写任何数据抓取代码之前,先确认云端 schedule routine 能否直接调用 Artifact 工具完成 redeploy。探针用的文件放在会话 scratchpad,不进项目仓库(用完即弃,与项目代码无关)。

**文件：**
- 创建(scratchpad,非项目仓库)：`/tmp/claude-1000/-home-wsl-08-work/14b3bc5b-adce-4d62-a341-aaa7959e17a3/scratchpad/probe_placeholder.html`
- 创建(项目仓库,记录结论)：`docs/decisions/0001-artifact-in-routine-feasibility.md`

- [ ] **步骤 1：写占位页面内容**

写入 `/tmp/claude-1000/-home-wsl-08-work/14b3bc5b-adce-4d62-a341-aaa7959e17a3/scratchpad/probe_placeholder.html`:

```html
<p>PROBE_MARKER: v0-not-yet-updated</p>
```

- [ ] **步骤 2：发布探针 Artifact**

调用 `Artifact` 工具:
```
file_path: "/tmp/claude-1000/-home-wsl-08-work/14b3bc5b-adce-4d62-a341-aaa7959e17a3/scratchpad/probe_placeholder.html"
title: "Lit Radar Probe"
description: "探针页面:验证云端 routine 能否重新发布 Artifact"
favicon: "🔬"
status: publish (默认)
```
记录返回的 URL,记为 `PROBE_URL`(下面步骤要原样代入)。

- [ ] **步骤 3：生成一次性 routine 所需的 uuid 和时间**

```bash
python3 -c "import uuid; print(str(uuid.uuid4()))"
date -u -d "+4 minutes" +%Y-%m-%dT%H:%M:%SZ
```
分别记为 `EVENT_UUID` 和 `RUN_ONCE_AT`。

- [ ] **步骤 4：创建一次性探针 routine**

调用 `RemoteTrigger`(先用 `ToolSearch select:RemoteTrigger` 加载 schema,若尚未加载):
```json
{
  "action": "create",
  "body": {
    "name": "lit-radar-artifact-probe",
    "run_once_at": "<RUN_ONCE_AT>",
    "job_config": {
      "ccr": {
        "environment_id": "env_01N5xPtBtmw6Mgtv21ctQhhc",
        "session_context": {
          "model": "claude-sonnet-5",
          "sources": [],
          "allowed_tools": ["Bash", "Write", "Artifact"]
        },
        "events": [
          {"data": {
            "uuid": "<EVENT_UUID>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {
              "role": "user",
              "content": "你是一个技术可行性探针任务,只做以下步骤,不要做任何其他事情,不要尝试变通方法:1) 用 Bash 运行 `date -u +%Y-%m-%dT%H:%M:%SZ` 拿到当前 UTC 时间字符串,记为 T。2) 用 Write 工具写文件 /tmp/probe_updated.html,内容为一行:`<p>PROBE_MARKER: v1-updated-by-cloud-routine-at-T</p>`(把 T 换成第1步拿到的真实时间字符串)。3) 调用 Artifact 工具,file_path 设为 /tmp/probe_updated.html,url 参数设为 '<PROBE_URL>',favicon 设为 '🔬'。4) 如果第3步调用失败或报错,原样完整输出错误信息;如果成功,输出 'PROBE OK'。"
            }
          }}
        ]
      }
    }
  }
}
```
把 `<PROBE_URL>` 替换成步骤2实际返回的 URL。记录响应里的 `trigger_id`,记为 `PROBE_TRIGGER_ID`。

- [ ] **步骤 5：等待 routine 触发**

```bash
sleep 300
```
(等待时间覆盖 4 分钟的 `run_once_at` 延迟 + 1 分钟余量)

- [ ] **步骤 6：检查探针页面是否被云端更新**

调用 `WebFetch`:
```
url: <PROBE_URL>
prompt: "返回页面里 PROBE_MARKER 后面的完整文字内容"
```
预期两种结果之一:
- 内容变成 `v1-updated-by-cloud-routine-at-...` → 探针 **PASS**
- 内容仍是 `v0-not-yet-updated`,或 WebFetch/routine 报错 → 探针 **FAIL**

- [ ] **步骤 7：查看 routine 执行状态作为辅助证据**

调用 `RemoteTrigger`:
```json
{"action": "get", "trigger_id": "<PROBE_TRIGGER_ID>"}
```
记录 `ended_reason` 字段(预期 `run_once_fired`)及响应中任何错误信息。

- [ ] **步骤 8：写决策文件**

创建 `docs/decisions/0001-artifact-in-routine-feasibility.md`,内容模板(把方括号部分替换成步骤6/7的真实结果):

```markdown
# 决策 0001:云端 schedule routine 能否直接调用 Artifact 工具

**探针时间：** [执行时的 UTC 时间]
**探针 Artifact URL：** [PROBE_URL]
**探针 routine trigger_id：** [PROBE_TRIGGER_ID]

## 证据

- WebFetch 检查探针页面内容:[步骤6实际返回的完整文字]
- RemoteTrigger get 响应:ended_reason=[值],其他相关字段=[值]

## 结论

[PASS / FAIL]

## 后续架构选择

- 若 PASS:采用任务 9 的 **路径 A(全自动)** —— 生产 routine 直接调用 Artifact 工具重新发布。
- 若 FAIL:采用任务 9 的 **路径 B(半自动)** —— 生产 routine 只把渲染好的 dist/dashboard.html 提交回仓库,本机用 `/loop` 定期拉取并调用 Artifact 发布。
```

- [ ] **步骤 9：Commit 决策文件**

```bash
cd /home/wsl/08_work/schizothoracinae-lit-radar
git add docs/decisions/0001-artifact-in-routine-feasibility.md
git commit -m "docs: 记录 Artifact-in-routine 可行性探针结果"
```

---

## 任务 1：项目骨架

**文件：**
- 创建：`requirements.txt`
- 创建：`pyproject.toml`
- 创建：`.gitignore`
- 创建：`README.md`
- 创建：`config/keywords.yaml`

- [ ] **步骤 1：requirements.txt**

```
PyYAML>=6.0,<7.0
pytest>=7.4,<9.0
```

- [ ] **步骤 2：pyproject.toml**

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

- [ ] **步骤 3：.gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **步骤 4：config/keywords.yaml**

```yaml
track_a:
  label: "裂腹鱼亚科物种精确检索"
  keywords:
    - "Schizothoracinae"
    - "Schizothorax"
    - "Gymnocypris"
    - "Schizopygopsis"
track_b:
  label: "群体遗传方法学前沿"
  keywords:
    - "polyploid population genetics"
    - "introgression gene flow detection"
    - "high-altitude adaptation fish evolution"
    - "allopolyploid genome phasing"
    - "ABBA-BABA D-statistics introgression"
```

- [ ] **步骤 5：README.md**

```markdown
# 裂腹鱼 / 群体遗传文献雷达

每日自动汇总裂腹鱼亚科(Schizothoracinae)物种文献与群体遗传方法学前沿文献,以 Claude Artifact 看板形式展示。

## 目录结构

见 `docs/superpowers/plans/2026-08-03-lit-radar-plan.md` 的"文件结构"章节。

## 本地运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/fetch.py      # 抓取最新文献,更新 data/data.json
python3 scripts/inject.py     # 把 data.json 嵌入模板,生成 dist/dashboard.html
pytest tests/ -v               # 跑单元测试
```

## 更新链路

1. GitHub Actions(`.github/workflows/fetch.yml`)每日 06:00 UTC 跑 `fetch.py` 并 commit `data/data.json`。
2. claude.ai schedule routine 每日 07:00 UTC 拉取最新 `data.json`,跑 `inject.py`,调用 Artifact 工具重新发布看板。具体路径(全自动/半自动)见 `docs/decisions/0001-artifact-in-routine-feasibility.md`。

## 关键词配置

编辑 `config/keywords.yaml` 即可调整检索范围,不需要改代码。

## 已知限制

- 数据来源:OpenAlex、PubMed(NCBI E-utilities)、bioRxiv(仅最近 10 天 + 关键词客户端过滤,因 bioRxiv API 本身不支持关键词搜索)。未接入 Semantic Scholar/Crossref/CORE/Unpaywall/database-lookup(MVP 阶段范围外)。
- 不做 AI 精读摘要/相关性打分。
- PubMed 数据来自 eSummary,不含摘要正文(MVP 阶段不额外调用 eFetch)。
```

- [ ] **步骤 6：Commit**

```bash
cd /home/wsl/08_work/schizothoracinae-lit-radar
git add requirements.txt pyproject.toml .gitignore config/keywords.yaml README.md
git commit -m "chore: 项目骨架(依赖、配置、README)"
```

---

## 任务 2：`scripts/fetch.py` 数据抓取脚本(TDD)

**文件：**
- 创建：`scripts/fetch.py`
- 测试：`tests/test_fetch.py`

- [ ] **步骤 1：写测试文件**

`tests/test_fetch.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.fetch import (
    reconstruct_openalex_abstract,
    merge_papers,
    compute_stats,
    fetch_openalex,
    fetch_biorxiv_recent,
)


def test_reconstruct_openalex_abstract_orders_words_by_position():
    inverted = {"Despite": [0], "growing": [1], "interest": [2]}
    assert reconstruct_openalex_abstract(inverted) == "Despite growing interest"


def test_reconstruct_openalex_abstract_handles_empty():
    assert reconstruct_openalex_abstract({}) == ""
    assert reconstruct_openalex_abstract(None) == ""


def test_merge_papers_dedups_by_id():
    existing = [{"id": "10.1/a", "title": "A", "date": "2026-01-01"}]
    new = [
        {"id": "10.1/a", "title": "A (dup)", "date": "2026-01-01"},
        {"id": "10.1/b", "title": "B", "date": "2026-01-02"},
    ]
    merged, added = merge_papers(existing, new)
    assert added == 1
    assert len(merged) == 2
    assert {p["id"] for p in merged} == {"10.1/a", "10.1/b"}


def test_merge_papers_sorts_by_date_desc():
    existing = [{"id": "1", "title": "old", "date": "2026-01-01"}]
    new = [{"id": "2", "title": "new", "date": "2026-06-01"}]
    merged, _ = merge_papers(existing, new)
    assert [p["id"] for p in merged] == ["2", "1"]


def test_compute_stats_counts_new_this_week_and_trend_length():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    papers = [
        {"date": "2026-08-01"},
        {"date": "2026-07-01"},
    ]
    stats = compute_stats(papers, now)
    assert stats["total_count"] == 2
    assert stats["new_this_week"] == 1
    assert len(stats["weekly_trend"]) == 6


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_parses_results(mock_get):
    mock_get.return_value = {
        "results": [{
            "doi": "https://doi.org/10.1/xyz",
            "title": "Test paper",
            "authorships": [{"author": {"display_name": "Jane Doe"}}],
            "primary_location": {"source": {"display_name": "Journal X"}},
            "publication_date": "2026-08-01",
            "id": "https://openalex.org/W1",
            "abstract_inverted_index": {"Hello": [0], "world": [1]},
        }]
    }
    papers = fetch_openalex("test", "2026-07-01", "A")
    assert len(papers) == 1
    p = papers[0]
    assert p["doi"] == "10.1/xyz"
    assert p["title"] == "Test paper"
    assert p["authors"] == ["Jane Doe"]
    assert p["journal"] == "Journal X"
    assert p["abstract"] == "Hello world"
    assert p["track"] == "A"
    assert p["source"] == "OpenAlex"


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_skips_results_without_title(mock_get):
    mock_get.return_value = {"results": [{"title": "", "doi": "10.1/x"}]}
    assert fetch_openalex("test", "2026-07-01", "A") == []


@patch("scripts.fetch.http_get_json")
def test_fetch_biorxiv_recent_filters_by_keyword(mock_get):
    mock_get.return_value = {
        "collection": [
            {"title": "Schizothorax genome", "abstract": "...", "doi": "10.1101/a",
             "date": "2026-08-01", "authors": "Li, X.; Wang, Y."},
            {"title": "Unrelated fruit fly study", "abstract": "...", "doi": "10.1101/b",
             "date": "2026-08-01", "authors": "Smith, A."},
        ]
    }
    papers = fetch_biorxiv_recent(["Schizothorax"], "A")
    assert len(papers) == 1
    assert papers[0]["title"] == "Schizothorax genome"
    assert papers[0]["authors"] == ["Li, X.", "Wang, Y."]
```

- [ ] **步骤 2：运行测试确认失败**

```bash
cd /home/wsl/08_work/schizothoracinae-lit-radar
pytest tests/test_fetch.py -v
```
预期:FAIL,报错 `ModuleNotFoundError: No module named 'scripts.fetch'` 或 `ImportError`(因为 `scripts/fetch.py` 还不存在)。

- [ ] **步骤 3：实现 scripts/fetch.py**

```python
#!/usr/bin/env python3
import json
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "data.json"
KEYWORDS_PATH = ROOT / "config" / "keywords.yaml"

LOOKBACK_DAYS = 7
CONTACT_EMAIL = "ccj13169@gmail.com"


def http_get_json(url, retries=3, backoff=2.0):
    headers = {"User-Agent": f"schizothoracinae-lit-radar/1.0 ({CONTACT_EMAIL})"}
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if attempt == retries - 1:
                print(f"WARN: giving up on {url}: {exc}", file=sys.stderr)
                return None
            time.sleep(backoff * (attempt + 1))
    return None


def reconstruct_openalex_abstract(inverted_index):
    if not inverted_index:
        return ""
    positions = {}
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions[i] = word
    return " ".join(positions[i] for i in sorted(positions.keys()))


def fetch_openalex(keyword, since_date, track):
    query = urllib.parse.quote(keyword)
    url = (
        "https://api.openalex.org/works"
        f"?search={query}"
        f"&filter=from_publication_date:{since_date}"
        f"&sort=publication_date:desc&per_page=50&mailto={CONTACT_EMAIL}"
    )
    data = http_get_json(url)
    if not data:
        return []
    papers = []
    for work in data.get("results", []):
        title = work.get("title") or ""
        if not title:
            continue
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        papers.append({
            "id": doi or work.get("id", ""),
            "title": title,
            "authors": [a["author"]["display_name"] for a in work.get("authorships", [])],
            "journal": (work.get("primary_location") or {}).get("source", {}).get("display_name", "") or "",
            "date": work.get("publication_date", ""),
            "doi": doi,
            "url": work.get("id", ""),
            "abstract": reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
            "track": track,
            "source": "OpenAlex",
        })
    return papers


def fetch_pubmed(keyword, since_date, track):
    term = urllib.parse.quote(f'{keyword} AND ("{since_date}"[PDAT] : "3000"[PDAT])')
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={term}&retmode=json&retmax=50&sort=pub_date"
        f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
    )
    search_data = http_get_json(search_url)
    if not search_data:
        return []
    pmids = search_data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return []
    time.sleep(0.4)
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={','.join(pmids)}&retmode=json"
        f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
    )
    summary_data = http_get_json(summary_url)
    if not summary_data:
        return []
    papers = []
    result = summary_data.get("result", {})
    for uid in result.get("uids", []):
        item = result.get(uid, {})
        doi = ""
        for aid in item.get("articleids", []):
            if aid.get("idtype") == "doi":
                doi = aid.get("value", "")
        papers.append({
            "id": doi or uid,
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])],
            "journal": item.get("fulljournalname", ""),
            "date": item.get("pubdate", ""),
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            "abstract": "",
            "track": track,
            "source": "PubMed",
        })
    return papers


def fetch_biorxiv_recent(keywords, track):
    url = "https://api.biorxiv.org/details/biorxiv/10d/0/json"
    data = http_get_json(url)
    if not data:
        return []
    lowered_keywords = [k.lower() for k in keywords]
    papers = []
    for item in data.get("collection", []):
        haystack = f"{item.get('title','')} {item.get('abstract','')}".lower()
        if not any(k in haystack for k in lowered_keywords):
            continue
        papers.append({
            "id": item.get("doi", ""),
            "title": item.get("title", ""),
            "authors": [a.strip() for a in item.get("authors", "").split(";") if a.strip()],
            "journal": "bioRxiv (preprint)",
            "date": item.get("date", ""),
            "doi": item.get("doi", ""),
            "url": f"https://doi.org/{item.get('doi','')}" if item.get("doi") else "",
            "abstract": item.get("abstract", ""),
            "track": track,
            "source": "bioRxiv",
        })
    return papers


def merge_papers(existing_papers, new_papers):
    by_id = {p["id"]: p for p in existing_papers if p.get("id")}
    added = 0
    for p in new_papers:
        key = p.get("id") or p.get("title", "").lower()
        if key and key not in by_id:
            by_id[key] = p
            added += 1
    merged = sorted(by_id.values(), key=lambda p: p.get("date", ""), reverse=True)
    return merged, added


def compute_stats(all_papers, now):
    total = len(all_papers)
    week_ago = (now - timedelta(days=7)).date().isoformat()
    new_this_week = sum(1 for p in all_papers if p.get("date", "") >= week_ago)
    trend = []
    for i in range(5, -1, -1):
        week_start = (now - timedelta(days=7 * (i + 1))).date()
        week_end = (now - timedelta(days=7 * i)).date()
        count = sum(
            1 for p in all_papers
            if week_start.isoformat() <= p.get("date", "") < week_end.isoformat()
        )
        trend.append({"week": week_start.strftime("%Y-W%V"), "count": count})
    return {"total_count": total, "new_this_week": new_this_week, "weekly_trend": trend}


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {
        "generated_at": "",
        "tracks": {
            "A": {"label": "", "keywords": [], "papers": []},
            "B": {"label": "", "keywords": [], "papers": []},
        },
        "stats": {"total_count": 0, "new_this_week": 0, "weekly_trend": []},
    }


def main():
    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    config = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))
    existing = load_existing()
    total_added = 0

    for track_id, cfg_key in (("A", "track_a"), ("B", "track_b")):
        track_cfg = config[cfg_key]
        track_state = existing["tracks"].setdefault(
            track_id, {"label": "", "keywords": [], "papers": []}
        )
        track_state["label"] = track_cfg["label"]
        track_state["keywords"] = track_cfg["keywords"]

        new_papers = []
        for kw in track_cfg["keywords"]:
            new_papers.extend(fetch_openalex(kw, since_date, track_id))
            time.sleep(0.2)
            new_papers.extend(fetch_pubmed(kw, since_date, track_id))
            time.sleep(0.4)
        new_papers.extend(fetch_biorxiv_recent(track_cfg["keywords"], track_id))

        merged, added = merge_papers(track_state["papers"], new_papers)
        track_state["papers"] = merged
        total_added += added

    all_papers = existing["tracks"]["A"]["papers"] + existing["tracks"]["B"]["papers"]
    existing["stats"] = compute_stats(all_papers, now)
    existing["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fetch.py done: +{total_added} new papers, total={len(all_papers)}")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 4：运行测试确认通过**

```bash
pytest tests/test_fetch.py -v
```
预期:全部 PASS(9 项测试)。

- [ ] **步骤 5：Commit**

```bash
git add scripts/fetch.py tests/test_fetch.py
git commit -m "feat: 双轨文献抓取脚本(OpenAlex/PubMed/bioRxiv)"
```

---

## 任务 3：委托 agy 生成 `template/dashboard.html`

**文件：**
- 创建(由 agy 产出,人工审查后保留)：`template/dashboard.html`

- [ ] **步骤 1：调用 agy CLI**

```bash
cd /home/wsl/08_work/schizothoracinae-lit-radar
mkdir -p template
agy --mode accept-edits -p "$(cat <<'EOF'
在当前目录下创建单个文件 template/dashboard.html,一个静态的科研文献看板前端模板。硬性约束(必须全部遵守,因为这个文件最终会被嵌入 claude.ai 的 Artifact 沙箱运行,该沙箱有严格 CSP):
1. 只能有这一个文件,不能引用任何外部资源——不能有 CDN <script src>、外部字体、外部图片、外部 CSS link。所有 CSS 和 JS 必须 inline 在 <style> 和 <script> 标签里。趋势图用纯 SVG/CSS 手写,不要用任何图表库。
2. 不要写 <!doctype>、<html>、<head>、<body> 标签,直接从内容本体开始写(比如 <style>...</style> 后面接 <div id="app">...</div>),这几个包裹标签会由外部框架自动加。可以写 <title> 标签。
3. 必须同时支持浅色和深色主题:用 @media (prefers-color-scheme: dark) 做默认判断,同时加 :root[data-theme="dark"] / :root[data-theme="light"] 选择器覆盖(未来外部框架会在根元素上设置 data-theme 属性,必须让它生效)。
4. 页面里唯一的数据来源是一个 JSON 占位符字符串,原样写在页面里:
   <script id="lit-radar-data" type="application/json">__LIT_RADAR_DATA__</script>
   不要改这个占位符的名字或格式,后续会有一个独立脚本把真实 JSON 内容原地替换这个字符串。
5. 这个 JSON 的结构长这样(写一段页面加载时用于解析展示的 JS,基于这个结构渲染,不要假设有其他字段):
{
  "generated_at": "2026-08-04T06:00:00Z",
  "tracks": {
    "A": {"label": "裂腹鱼亚科物种精确检索", "keywords": ["Schizothoracinae", "..."], "papers": [ {"id": "...", "title": "...", "authors": ["...", "..."], "journal": "...", "date": "2026-08-01", "doi": "...", "url": "https://...", "abstract": "...", "track": "A", "source": "OpenAlex"} ]},
    "B": {"label": "群体遗传方法学前沿", "keywords": ["..."], "papers": [ ... 同样结构,source 可能是 OpenAlex/PubMed/bioRxiv ... ]}
  },
  "stats": {"total_count": 123, "new_this_week": 4, "weekly_trend": [{"week": "2026-W28", "count": 3}, {"week": "2026-W29", "count": 5}]}
}
6. 页面功能:顶部显示 generated_at(格式化成易读中文日期时间)、total_count、new_this_week 高亮徽标、weekly_trend 用一个简单的 SVG 柱状或折线小图表(6 个数据点);双轨 Tab 切换(A/B,用 label 做 Tab 标题);每条文献展示标题(可点击跳转 url 或 doi 链接,新标签打开)、作者(最多显示前 3 位+"等"如果更多)、期刊/来源、日期、来源数据库标签(source 字段,不同来源用不同颜色徽标,比如 OpenAlex 蓝色系、PubMed 绿色系、bioRxiv 橙色系)、摘要(默认折叠,点击标题展开/收起);顶部一个搜索框按标题/摘要关键词实时过滤(纯前端 JS,不用请求任何接口);一个按 source 筛选的多选按钮组;文献列表默认按 date 降序排列,如果 new_this_week 范围内的文献应有醒目的"NEW"小标签。
7. 整个页面要响应式(移动端和桌面端都能看),宽表格/图表类内容如果要横向溢出必须放进有 overflow-x:auto 的容器里,不能让整个页面横向滚动。
8. 不要写任何注释解释代码在做什么这类废话注释,保持代码整洁。
9. 完成后不需要额外附加说明文字,直接把文件写好就行。
EOF
)"
```

- [ ] **步骤 2：人工检查产出是否满足硬性约束**

```bash
grep -n "__LIT_RADAR_DATA__" template/dashboard.html
grep -niE "<!doctype|<html|<head|<body" template/dashboard.html
grep -niE "cdn\.|googleapis\.com|<link rel=\"stylesheet\" href=\"http|<script src=\"http" template/dashboard.html
```
预期:第一条命令有输出(占位符存在);第二、三条命令**无输出**(说明没有违反 Artifact CSP 约束的标签/外部资源)。如果第二、三条有输出,回到步骤 1 修改 prompt 强调对应约束重新生成,直到满足为止。

- [ ] **步骤 3：Commit**

```bash
git add template/dashboard.html
git commit -m "feat: agy 生成的文献看板前端模板"
```

---

## 任务 4：`scripts/inject.py` 数据注入脚本(TDD)

**文件：**
- 创建：`scripts/inject.py`
- 测试：`tests/test_inject.py`

- [ ] **步骤 1：写测试文件**

`tests/test_inject.py`:

```python
import pytest

from scripts.inject import render, PLACEHOLDER


def test_render_replaces_placeholder():
    template = f'<div>{PLACEHOLDER}</div>'
    result = render(template, {"a": 1})
    assert PLACEHOLDER not in result
    assert '{"a": 1}' in result


def test_render_escapes_script_close_tag_in_data():
    template = f'<script id="lit-radar-data" type="application/json">{PLACEHOLDER}</script>'
    data = {"title": "</script><script>alert(1)</script>"}
    result = render(template, data)
    assert result.count("</script>") == 1


def test_render_missing_placeholder_raises():
    with pytest.raises(ValueError):
        render("<div>no placeholder here</div>", {"a": 1})
```

- [ ] **步骤 2：运行测试确认失败**

```bash
pytest tests/test_inject.py -v
```
预期:FAIL,`ModuleNotFoundError: No module named 'scripts.inject'`。

- [ ] **步骤 3：实现 scripts/inject.py**

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ROOT / "template" / "dashboard.html"
DATA_PATH = ROOT / "data" / "data.json"
OUTPUT_PATH = ROOT / "dist" / "dashboard.html"
PLACEHOLDER = "__LIT_RADAR_DATA__"


def render(template_str, data_obj):
    if PLACEHOLDER not in template_str:
        raise ValueError(f"placeholder {PLACEHOLDER} not found in template")
    data_json_str = json.dumps(data_obj, ensure_ascii=False).replace("</script>", "<\\/script>")
    return template_str.replace(PLACEHOLDER, data_json_str)


def main():
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template not found at {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    if not DATA_PATH.exists():
        print(f"ERROR: data not found at {DATA_PATH}", file=sys.stderr)
        sys.exit(1)

    template_str = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_obj = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    output = render(template_str, data_obj)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"inject.py done: wrote {OUTPUT_PATH} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
```

- [ ] **步骤 4：运行测试确认通过**

```bash
pytest tests/test_inject.py -v
```
预期:全部 PASS(3 项测试)。

- [ ] **步骤 5：Commit**

```bash
git add scripts/inject.py tests/test_inject.py
git commit -m "feat: 数据注入脚本(data.json -> dashboard.html)"
```

---

## 任务 5：本地端到端验证 + 首次发布 Artifact

**文件：**
- 创建：`data/data.json`(真实抓取结果)
- 创建：`dist/dashboard.html`(真实渲染结果)
- 创建：`config/artifact_url.txt`(记录首次发布的 Artifact URL,供后续 routine 使用)

- [ ] **步骤 1：真实跑一次抓取**

```bash
cd /home/wsl/08_work/schizothoracinae-lit-radar
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/fetch.py
```
预期:打印 `fetch.py done: +N new papers, total=M`,且 `data/data.json` 存在且非空。如果 `total=0`(比如 OpenAlex/PubMed 当天恰好没有匹配结果),属于正常情况,继续下一步(看板要能正确展示"暂无新文献"这种空状态,如果任务3的模板对空 papers 数组处理有问题,回到任务3修复)。

- [ ] **步骤 2：渲染最终页面**

```bash
python3 scripts/inject.py
```
预期:打印 `inject.py done: wrote .../dist/dashboard.html (N bytes)`。

- [ ] **步骤 3：首次发布 Artifact**

调用 `Artifact` 工具:
```
file_path: "/home/wsl/08_work/schizothoracinae-lit-radar/dist/dashboard.html"
title: "裂腹鱼/群体遗传文献雷达"
description: "裂腹鱼亚科物种文献与群体遗传方法学前沿的每日自动更新看板"
favicon: "🐟"
status: publish (默认)
```
在浏览器打开返回的 URL,人工检查:双轨 Tab 能否切换、搜索框能否过滤、来源筛选按钮能否工作、深色/浅色模式切换是否都正常。有问题回到任务3调整 agy prompt 重新生成模板。

- [ ] **步骤 4：记录 Artifact URL**

写入 `config/artifact_url.txt`(内容为步骤3返回的 URL,仅一行,无需其他内容)。

- [ ] **步骤 5：Commit**

```bash
git add data/data.json dist/dashboard.html config/artifact_url.txt
git commit -m "chore: 首次真实抓取数据 + 首次发布 Artifact"
```

---

## 任务 6：GitHub 仓库创建与 Actions 定时抓取

**文件：**
- 创建：`.github/workflows/fetch.yml`

- [ ] **步骤 1：写 workflow 文件**

```yaml
name: Fetch literature daily

on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python3 scripts/fetch.py
      - name: Commit updated data
        run: |
          git config user.name "lit-radar-bot"
          git config user.email "actions@users.noreply.github.com"
          git add data/data.json
          if git diff --cached --quiet; then
            echo "no changes"
          else
            git commit -m "chore: update data.json $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          fi
```

- [ ] **步骤 2：本地校验 YAML 语法**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/fetch.yml'))" && echo "YAML OK"
```
预期:打印 `YAML OK`,无异常抛出。

- [ ] **步骤 3：Commit 并创建 GitHub 仓库**

```bash
git add .github/workflows/fetch.yml
git commit -m "ci: 每日定时抓取 workflow"
gh repo create schizothoracinae-lit-radar --public --source=. --remote=origin --push
```
预期:命令成功,输出仓库 URL(形如 `https://github.com/<login>/schizothoracinae-lit-radar`)。记为 `REPO_URL`。

- [ ] **步骤 4：手动触发一次验证 Actions 能跑通**

```bash
gh workflow run fetch.yml --repo <REPO_URL 去掉 https://github.com/ 前缀,即 owner/repo 形式>
sleep 30
gh run list --workflow=fetch.yml --repo <owner/repo> --limit 1
```
把返回的 run ID 代入下一条命令等待完成:
```bash
gh run watch <RUN_ID> --repo <owner/repo>
```
预期:最终状态为 `completed success`。如果失败,用 `gh run view <RUN_ID> --repo <owner/repo> --log-failed` 查看具体报错并修复 `fetch.py` 或 workflow 文件。

---

## 任务 7：生产用 claude.ai schedule routine

**前置条件：** 先读 `docs/decisions/0001-artifact-in-routine-feasibility.md` 里任务 0 记录的结论,决定走路径 A 还是路径 B。

**文件：** 无新文件(routine 配置存在于 claude.ai 侧,不在仓库里)。

- [ ] **步骤 1：生成 uuid**

```bash
python3 -c "import uuid; print(str(uuid.uuid4()))"
```
记为 `PROD_EVENT_UUID`。

### 若任务 0 结论为 PASS —— 路径 A(全自动)

- [ ] **步骤 2A：创建每日 07:00 UTC 的 cron routine**

调用 `RemoteTrigger`:
```json
{
  "action": "create",
  "body": {
    "name": "lit-radar-daily-publish",
    "cron_expression": "0 7 * * *",
    "enabled": true,
    "job_config": {
      "ccr": {
        "environment_id": "env_01N5xPtBtmw6Mgtv21ctQhhc",
        "session_context": {
          "model": "claude-sonnet-5",
          "sources": [{"git_repository": {"url": "<REPO_URL>"}}],
          "allowed_tools": ["Bash", "Read", "Write", "Artifact"]
        },
        "events": [
          {"data": {
            "uuid": "<PROD_EVENT_UUID>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {
              "role": "user",
              "content": "仓库已 clone 到当前工作目录。读取 config/artifact_url.txt 得到 ARTIFACT_URL(文件内容就是 URL,去除首尾空白)。运行 `python3 scripts/inject.py`,确认生成了 dist/dashboard.html。然后调用 Artifact 工具:file_path='dist/dashboard.html',url=ARTIFACT_URL,favicon='🐟',title='裂腹鱼/群体遗传文献雷达',description='裂腹鱼亚科物种文献与群体遗传方法学前沿的每日自动更新看板'。如果 inject.py 报错或 Artifact 调用失败,原样输出完整错误信息,不要尝试变通方法或重试。成功则输出 'DAILY PUBLISH OK'。"
            }
          }}
        ]
      }
    }
  }
}
```

- [ ] **步骤 3A：验证首次运行**

```
RemoteTrigger: {"action": "run", "trigger_id": "<返回的 trigger_id>"}
```
等待约 2 分钟后打开 `config/artifact_url.txt` 里记录的 URL,确认页面 `generated_at` 字段更新为最新时间。

### 若任务 0 结论为 FAIL —— 路径 B(半自动)

- [ ] **步骤 2B：创建每日 07:00 UTC 的 cron routine(只提交渲染结果,不调 Artifact)**

```json
{
  "action": "create",
  "body": {
    "name": "lit-radar-daily-render",
    "cron_expression": "0 7 * * *",
    "enabled": true,
    "job_config": {
      "ccr": {
        "environment_id": "env_01N5xPtBtmw6Mgtv21ctQhhc",
        "session_context": {
          "model": "claude-sonnet-5",
          "sources": [{"git_repository": {"url": "<REPO_URL>"}}],
          "allowed_tools": ["Bash", "Read", "Write"]
        },
        "events": [
          {"data": {
            "uuid": "<PROD_EVENT_UUID>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {
              "role": "user",
              "content": "仓库已 clone 到当前工作目录。运行 `python3 scripts/inject.py` 生成 dist/dashboard.html。用 git 配置 user.name='lit-radar-bot', user.email='actions@users.noreply.github.com',把 dist/dashboard.html 的变化 commit(如果和上次相比没有变化就跳过 commit)并 push 回仓库。如果 inject.py 报错,原样输出完整错误信息,不要尝试变通方法。"
            }
          }}
        ]
      }
    }
  }
}
```

- [ ] **步骤 3B：本机建一个每日重新发布的 `/loop`**

在本机 Claude Code 会话里运行:
```
/loop 使用 Bash 拉取 <REPO_URL> 仓库最新的 dist/dashboard.html(git pull 或 GitHub API 均可),调用 Artifact 工具以 file_path 指向它、url 设为 config/artifact_url.txt 里记录的地址重新发布。每次执行完检查 generated_at 字段是否比上次新,如果相同就跳过发布避免无意义重发。
```
按提示设置为每日一次(与 routine 的 07:00 UTC 错开几分钟,比如本机时间对应 07:10 UTC 之后)。

**限制说明：** 路径 B 依赖本机保留一个可用的 `/loop` 会话,不是纯云端全自动——这是任务 0 探针 FAIL 时唯一现实的退路,已在设计规格第 8 节写明。

---

## 自检记录

- **规格覆盖度：** 领域范围(任务1步骤4)、数据源(任务2)、信息颗粒度(任务2的 paper 字段)、看板功能(任务3的 agy prompt 第6点逐项对应规格第5节)、更新链路(任务0+任务6+任务7)、agy 职责边界(任务3限定为一次性)、已知风险验证(任务0)均有对应任务覆盖。
- **占位符扫描：** 除任务0步骤2/4/8中标注为"运行时真实值代入"的 `<PROBE_URL>` 等字段外,无遗留 TODO/待定。这些字段的性质是"依赖前序步骤真实执行结果"而非设计缺口。
- **类型一致性：** `paper` 字典字段名(`id`/`title`/`authors`/`journal`/`date`/`doi`/`url`/`abstract`/`track`/`source`)在 `fetch.py`、agy prompt 描述的 JSON 结构、`inject.py` 测试中保持一致。`PLACEHOLDER`/`__LIT_RADAR_DATA__` 字符串在任务3的 agy prompt、任务4的 `inject.py`/测试中一致。
