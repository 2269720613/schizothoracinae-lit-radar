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
2. 本机 `/loop`(每小时轮询)拉取仓库最新 `data.json` → 跑 `inject.py` 重新渲染 → 比较 `generated_at` 判断数据是否有更新 → 有更新才调用 Artifact 工具,以 `config/artifact_url.txt` 记录的 URL 重新发布看板。

原计划里"claude.ai schedule routine 每日拉取数据并自动渲染发布"这一环,经过两轮真实测试(`docs/decisions/0001-artifact-in-routine-feasibility.md` 确认云端 routine 无法调用 Artifact 工具;`docs/decisions/0002-cloud-routine-cannot-push.md` 进一步确认云端 routine 连 push 代码到仓库都做不到)后已放弃,改为上面的本机 `/loop` 方案。代价是"渲染+发布"这一步需要本机保留一个运行着 `/loop` 的 Claude Code 会话,不是纯云端全自动。

## 关键词配置

编辑 `config/keywords.yaml` 即可调整检索范围,不需要改代码。

## 已知限制

- 数据来源:OpenAlex、PubMed(NCBI E-utilities)、bioRxiv(仅最近 10 天 + 关键词客户端过滤,因 bioRxiv API 本身不支持关键词搜索)。未接入 Semantic Scholar/Crossref/CORE/Unpaywall/database-lookup(MVP 阶段范围外)。
- 不做 AI 精读摘要/相关性打分。
- PubMed 数据来自 eSummary,不含摘要正文(MVP 阶段不额外调用 eFetch)。
- Track A(裂腹鱼亚科物种精确检索)在 OpenAlex 上使用的是全文检索(`search=` 参数,匹配标题+摘要+全文索引),而非仅限标题/摘要的定向字段搜索。首次真实抓取(2026-08-04)观察到约半数结果是被属名字符串误匹配的弱相关噪声,例如 GBIF 物种分布下载数据集(标题含 "Occurrence Download")、无关虾类/其他鱼类研究、古生物学论文等,这些结果并非真正围绕裂腹鱼亚科展开。后续可考虑:改用 OpenAlex 的 `title_and_abstract.search` 等定向字段过滤,或增加 `filter=type:article` 排除 dataset/其他非论文类型,以提升精确率。
