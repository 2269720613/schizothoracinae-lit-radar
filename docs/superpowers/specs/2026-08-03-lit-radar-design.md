# 裂腹鱼/群体遗传文献雷达 — 设计规格

日期:2026-08-03
状态:已批准,待写实现计划

## 1. 目标与用户

面向裂腹鱼亚科(Schizothoracinae)与群体遗传方法学研究者的"科研前沿文献实时看板"。目标是不用手动逐个数据库检索,每天自动汇总相关新文献,以可分享的网页形式呈现。

## 2. 领域范围(双轨)

- **轨道 A(精确检索)**:裂腹鱼亚科相关属/种名——`Schizothoracinae`, `Gymnocypris`, `Schizopygopsis`, `Schizothorax` 等。
- **轨道 B(方法学前沿)**:不限物种,追踪群体遗传方法学关键词——多倍体基因组学、渐渗/基因流检测(introgression/gene flow)、高原适应性演化等。

两轨在看板上分区/分 Tab 展示,数据结构上以 `track: "A"|"B"` 字段区分。

## 3. 数据源

- 使用 `paper-lookup` skill 记录的 REST API 规范(PubMed, PMC, bioRxiv, medRxiv, arXiv, OpenAlex, Crossref, Semantic Scholar, CORE, Unpaywall),由抓取脚本直接调用,不依赖 Claude Code 运行时。
- `database-lookup`(109 个科研数据库)本轮**不接入**——它偏数据集/数据库检索,与"文献雷达"定位不完全贴合,留作后续扩展项。

## 4. 信息颗粒度

每条记录:标题、作者、期刊/预印本平台、发表日期、DOI 链接、原始摘要、`track` 标签、来源数据库标签。不做 AI 二次精读/打分(MVP 阶段不引入 LLM API 调用,保持 GitHub Actions 无需额外 API key、运行稳定)。

## 5. 看板功能

- 关键词搜索 + 按来源数据库/时间筛选
- 双轨 Tab 切换(轨道 A / 轨道 B)
- "本周新增"高亮 + 累计收录总量趋势小图表
- 按来源数据库分组标签(PubMed/bioRxiv/OpenAlex 等徽标)

## 6. 架构与更新链路

```
schizothoracinae-lit-radar/               (新建独立 GitHub 仓库)
├── scripts/fetch.py          # 调 paper-lookup API 规范做双轨抓取,写 data/data.json
├── data/data.json            # 抓取结果(按 track + source 分类)
├── template/dashboard.html   # agy 一次性交付的静态 HTML/CSS/JS 模板,数据位留占位符
├── scripts/inject.py         # 把 data.json 嵌入 dashboard.html 占位符,生成最终页面
└── .github/workflows/fetch.yml   # 每日 06:00 UTC 跑 fetch.py 并 commit data.json
```

每日更新链路(两段式,均为定时无人值守):

1. **GitHub Actions**(06:00 UTC):跑 `fetch.py` → 写入/更新 `data/data.json` → commit 到仓库。
2. **claude.ai schedule 云端 routine**(07:00 UTC):`WebFetch`/`Bash` 拉取仓库最新 `data/data.json`(经 raw.githubusercontent.com)→ 跑 `inject.py` 生成最终 HTML → 调用 `Artifact` 工具,以 `url:` 参数指向已发布的同一 Artifact URL 重新发布(redeploy),实现覆盖式刷新。

页面始终保持**完全静态可公开分享**(不使用 `mcp` 运行时能力,因为该能力会导致页面无法公开分享)。

## 7. 前端职责边界(agy)

`agy`(antigravity CLI)只在**实现阶段一次性**交付 `template/dashboard.html`:布局、双轨 Tab、搜索/筛选交互、本周新增高亮、趋势小图表、来源标签的静态模板,数据留占位符。之后的每日自动刷新只是"数据注入 + 重新发布",不再调用 agy。

## 8. 已知风险 / 待验证事项

- **云端 schedule routine 能否直接调用 Artifact 工具尚未验证**。`schedule` 技能的 `allowed_tools` 示例只列出了 Bash/Read/Write/Edit/Glob/Grep,未明确 Artifact 工具在云端 CCR 会话中的可用性。
  - **验证计划**:实现阶段第一步就搭一个最小化的 routine 测试(拉一个固定字符串→尝试调 Artifact 重新发布),先确认可行性,再继续搭完整流水线。
  - **退路**:若云端 routine 无法调用 Artifact 工具,则该步骤降级为——routine 只负责把渲染好的最终 HTML 提交回仓库,由用户/我在本地 Claude Code 会话里做最后一步"读取仓库最新 HTML → 调 Artifact 发布",退化为半自动更新(仍是"定时+人工确认一次点击"级别的自动化,而非全自动)。

## 9. 明确排除的范围(YAGNI)

- 不做 AI 精读摘要/相关性打分(MVP 阶段)
- 不接入 `database-lookup`(留后续)
- 不使用 `mcp` 运行时能力做浏览器端实时拉取(会牺牲页面公开分享能力)
- 不做用户账号/个性化订阅系统
