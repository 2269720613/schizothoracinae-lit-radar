# 裂腹鱼 / 群体遗传文献雷达

每日自动汇总裂腹鱼亚科(Schizothoracinae)物种文献与群体遗传方法学前沿文献,按期刊质量分层后以静态网站(GitHub Pages)展示。

**在线地址:** https://2269720613.github.io/schizothoracinae-lit-radar/

## 本地运行

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/fetch.py      # 抓取最新文献 + 分级,更新 data/data.json
python3 scripts/inject.py     # 把 data.json 嵌入模板,生成 dist/dashboard.html
pytest tests/ -v              # 跑单元测试
```

本地直接用浏览器打开 `dist/dashboard.html` 即可预览。

## 更新链路(全自动云端)

1. GitHub Actions(`.github/workflows/fetch.yml`)每日 06:00 UTC 触发。
2. **fetch job:** 跑 `fetch.py`(抓取 + 分级)→ `inject.py`(渲染 `dist/dashboard.html`)→ 提交 `data/data.json` 与 `dist/dashboard.html`。
3. **deploy job:** 重新 `inject.py` → 把 `dist/dashboard.html` 复制为 `_site/index.html` → 通过 `actions/deploy-pages` 发布到 GitHub Pages。

> 首次部署前需在仓库 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**,否则 deploy job 会失败。此后无需本机常驻会话(已取代早先依赖 Claude `/loop` + Artifact 的方案,相关决策记录见 `docs/decisions/`)。

## 质量分级(高质量文献筛选)

看板按期刊质量分为四层,默认隐藏噪声层:

| 层级 | 判定 | 前端 |
|---|---|---|
| **T1 经典** | 命中 `config/journal_tiers.yaml` 白名单(手工维护的核心刊) | 金色徽章 |
| **T2 优质** | 未入白名单,但 OpenAlex Sources 指标达标(`type=journal` + `is_core` + h-index 或 2yr-citedness 超阈值) | 绿色徽章 |
| **T3 一般** | 有正规期刊名但未达 T2 | 灰色徽章 |
| **噪声** | 标题命中噪声词 / 无期刊来源 / 非论文类型 | 默认隐藏,可勾选展开 |

- **指标来源:** OpenAlex Works API 内嵌的 source 不含 `summary_stats`(实测为 null),故 `fetch.py` 收集唯一 source ID 后批量(每请求 50 个)调用 OpenAlex **Sources API** 补全 h-index / 2yr-citedness。
- **检索收窄:** OpenAlex 改用 `filter=title_and_abstract.search` + `type:article`,只匹配标题/摘要并排除数据集等非论文类型,显著降低误匹配噪声(如 GBIF "Occurrence Download" 数据集)。
- **bioRxiv 预印本:** 方法学前沿(Track B)计为 T2,物种轨(Track A)计为 T3。

## 配置

- `config/keywords.yaml`:调整检索关键词/主题轨,不需改代码。
- `config/journal_tiers.yaml`:维护经典期刊白名单、T2 阈值、噪声词。想加刊直接往对应 track 追加一行小写刊名即可,下次抓取生效(且会对已收录文献重新分级)。

## 已知限制

- 数据来源:OpenAlex、PubMed(NCBI E-utilities,仅 eSummary 无摘要正文)、bioRxiv(最近 10 天 + 客户端关键词过滤)。
- 期刊指标用 OpenAlex 的 h-index / 2yr-citedness,无官方 Impact Factor;PubMed 记录无 OpenAlex source ID,只能靠白名单判 T1,否则落 T3。
- 历史 `data.json` 记录缺少新增的 source ID 字段,首次运行时按期刊名判级(多为 T3),随后续抓取中重新命中的记录逐步补全指标并可能升入 T2。
- 不做 AI 精读摘要/语义相关性打分。
