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

## Obsidian 每日精选同步(本机 Windows 计划任务)

GitHub Actions 负责"抓取→分级→发布",**每日精选到 Obsidian**由本机 Windows 计划任务完成:

1. **脚本** `scripts/obsidian_digest.py`:从 jsdelivr CDN / GitHub raw 拉取最新 `data/data.json`,按"期刊层级(T1→T2→T3)+时效+与项目主线相关性"四轨各精选 Top 5,生成日报写入 Obsidian。
2. **输出** `D:\笔记本\文献阅读\文献阅读\文献精读\文献雷达\YYYY-MM-DD.md`(Obsidian 库 `文献精读` 下)。
3. **去重** `文献雷达\.state.json`:按日期记录已推送论文,同日多次运行取并集,跨日不重复。
4. **调度** Windows 计划任务 `LitRadar_ObsidianDigest`,每日 15:30(北京时间,在云端 14:00 抓取之后)运行 `D:\lit-radar\scripts\run_digest.ps1` → `C:\Python314\python.exe obsidian_digest.py`,日志见 `D:\lit-radar\logs\digest_log.txt`。
5. **容错** 对 4 个 CDN 数据源各重试 2 次,总预算 70s 硬超时,包装器 200s 进程级强杀,不会挂死;网络全挂时快速失败并记日志,不产生脏数据。

> 精选口径反映本项目研究主线(裂腹鱼/多倍化·再二倍化/着丝粒/第四纪古气候)。想调整每轨篇数或关注词,改脚本顶部 `RELEVANCE` 与 `--top` 参数即可。

## Obsidian 精选论文深度精读(AI 精读)

每日精选不只给条目列表,还按领域生成 **DeepPaperNote 风格精读笔记**(核心信息/一句话总结/研究问题/创新点/方法/关键结果/摘要翻译/对本项目意义/局限),直接写入 Obsidian 主题目录,与看板四领域一一对应:

| 领域轨 | Obsidian 目录 |
|---|---|
| A 裂腹鱼亚科 | `文献精读\裂腹鱼亚科\` |
| B 生物/生信演化分析 | `文献精读\演化生物学\` |
| C 着丝粒研究 | `文献精读\着丝粒生物学\` |
| D 古地理古气候 | `文献精读\古气候基因组学\` |

1. **脚本** `scripts/obsidian_deepread.py`:读取当日精选(状态文件),按 DOI 从 `data.json` 还原论文,自动映射主题目录并生成骨架笔记(元数据+摘要+待精读结构)。`--dry-run` 打印清单,`--scaffold` 写骨架文件。
2. **精读合成** 由 AI 完成:骨架笔记的"一句话总结/研究问题/创新点/方法/结果/意义/局限"由 AI 结合摘要与领域背景精读后填充,输出完整笔记 `<作者><年份>_<短标题>.zh-CN.md`。
3. **摘要补齐** 数据源未带摘要的论文(PubMed 无摘要字段),精读前从 PubMed E-utilities 按 PMID 拉取全文摘要后再合成。
4. **去重** 同一 DOI 已存在精读笔记则跳过(如黑麦着丝粒 `Chen2026_rye_centromere`),不重复建。

> 运行方式: `python scripts/obsidian_deepread.py --date YYYY-MM-DD --dry-run` 查看当日待精读清单;对某日精读 = 上述脚本 + AI 合成。


## 配置

- `config/keywords.yaml`:调整四条主题轨的检索关键词,不需改代码。
- `config/journal_tiers.yaml`:维护顶刊白名单 `whitelist_top`、鱼类轨白名单 `whitelist_fish`、鱼类标题模式 `fish_title_patterns`、T2 阈值、噪声词、主题排除词与 `min_tier`。想加刊直接往对应列表追加一行小写刊名即可,下次抓取生效(且会对已收录文献重新分级)。

## 已知限制

- 数据来源:OpenAlex、PubMed(NCBI E-utilities,仅 eSummary 无摘要正文)、bioRxiv(最近 10 天 + 客户端关键词过滤)。
- 期刊指标用 OpenAlex 的 h-index / 2yr-citedness,无官方 Impact Factor;PubMed 命中缺 source ID,由刊名回填解析,解析不出的落 T3(鱼类)或噪声(非鱼类)。
- 历史 `data.json` 记录缺少新增的 source ID 字段,首次运行时按期刊名判级,随后续抓取中重新命中的记录逐步补全指标并可能升入 T2。
- 不做 AI 精读摘要/语义相关性打分。
