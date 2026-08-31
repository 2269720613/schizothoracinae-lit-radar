# 裂腹鱼 / 演化基因组学文献雷达

每日自动汇总四个主题轨的文献并按期刊质量分层,以静态网站(GitHub Pages)展示:

| 轨 | 主题 | 标准 |
|---|---|---|
| **A** | 裂腹鱼亚科物种精确检索(Schizothoracinae/Schizothorax/Gymnocypris/Schizopygopsis) | 鱼类轨:一/二区 top 期刊(见下) |
| **B** | 生物/生信演化分析(多倍体群体遗传、渐渗、高海拔适应等) | 非鱼类:仅顶刊/子刊 |
| **C** | 着丝粒研究(着丝粒演化、组装、卫星 DNA、holocentromere、CENP-A) | 非鱼类:仅顶刊/子刊 |
| **D** | 古地理古气候 × 基因组演化(古水系、第四纪系统地理、构造抬升与分化) | 非鱼类:仅顶刊/子刊 |

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

## 质量分级(双标准筛选)

看板按期刊质量分为四层,默认隐藏噪声层。**鱼类研究**(A 轨全部,或其他轨标题命中 `fish_title_patterns` 词首匹配)与**非鱼类研究**走两套标准:

| 层级 | 鱼类研究 | 非鱼类研究 | 前端 |
|---|---|---|---|
| **T1 经典** | 命中 `whitelist_fish`(一/二区 top) | 命中 `whitelist_top`(顶刊/子刊) | 金色徽章 |
| **T2 优质** | `whitelist_fish` 未命中但 OpenAlex 指标达标(`type=journal`+`is_core`+阈值) | 不可达(预印本除外) | 绿色徽章 |
| **T3 一般** | bioRxiv 预印本 | bioRxiv 预印本 | 灰色徽章 |
| **噪声** | 噪声词/主题排除词/无期刊来源/低于 `min_tier` | 同左 | 默认隐藏,可勾选展开 |

- **双标准判定:** 标题词首锚定匹配(`\bfish` 命中 fish/fishery,不命中 catfish)只放宽期刊门槛,不会隐藏论文;false positive 的代价仅是门槛放宽。
- **主题排除:** `exclude_title_patterns`(应激/胁迫控制实验类标题词)优先级最高,连白名单期刊和 bioRxiv 预印本一起降为噪声。
- **层级下限:** `min_tier: 2` 表示只保留 T1/T2,原 T3 直接降为噪声隐藏,对已收录文献回溯生效;改回 3 即恢复显示。
- **指标来源:** OpenAlex Works API 内嵌的 source 不含 `summary_stats`(实测为 null),故 `fetch.py` 收集唯一 source ID 后批量(每请求 50 个)调用 OpenAlex **Sources API** 补全 h-index / 2yr-citedness。
- **检索收窄:** OpenAlex 改用 `filter=title_and_abstract.search` + `type:article`,只匹配标题/摘要并排除数据集等非论文类型,显著降低误匹配噪声(如 GBIF "Occurrence Download" 数据集)。
- **Source ID 回填:** 每期抓取会对缺 `openalex_source_id` 的记录(PubMed 命中与历史数据)按刊名查 OpenAlex Sources API 回填,使 T2 指标判级适用于存量;查不到的(预印本库/数据仓库)以 null 记入 `data/openalex_source_cache.json` 负缓存,避免每期重复请求。删掉该文件即可强制重新解析。

## 近五年回填

日常运行只抓最近 7 天增量。首次接入新轨/新标准后,用回填模式一次拉满近五年文献:

```bash
python3 scripts/fetch.py --backfill   # 窗口 = 5×365 天,每关键词上限 1000 篇
```

回填与常规抓取共用同一套分级/去重/回填 source ID 逻辑,产出直接覆盖 `data/data.json`。

## 配置

- `config/keywords.yaml`:调整四条主题轨的检索关键词,不需改代码。
- `config/journal_tiers.yaml`:维护顶刊白名单 `whitelist_top`、鱼类轨白名单 `whitelist_fish`、鱼类标题模式 `fish_title_patterns`、T2 阈值、噪声词、主题排除词与 `min_tier`。想加刊直接往对应列表追加一行小写刊名即可,下次抓取生效(且会对已收录文献重新分级)。

## 已知限制

- 数据来源:OpenAlex、PubMed(NCBI E-utilities,仅 eSummary 无摘要正文)、bioRxiv(最近 10 天 + 客户端关键词过滤)。
- 期刊指标用 OpenAlex 的 h-index / 2yr-citedness,无官方 Impact Factor;PubMed 命中缺 source ID,由刊名回填解析,解析不出的落 T3(鱼类)或噪声(非鱼类)。
- 历史 `data.json` 记录缺少新增的 source ID 字段,首次运行时按期刊名判级,随后续抓取中重新命中的记录逐步补全指标并可能升入 T2。
- 不做 AI 精读摘要/语义相关性打分。
