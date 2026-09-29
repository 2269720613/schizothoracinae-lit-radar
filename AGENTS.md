# AGENTS.md — 文献雷达 × 精选精读工作流（任何 Agent 的接入契约）

> 无论你来自 Claude Code、CodeBuddy、Doubao 还是其他 Agent：进入本仓库后，先读本文件，
> 再跑 `python3 scripts/env_check.py` 确认环境就绪，然后按「每日流水线」执行。

## 1. 这是什么

一个**四领域文献雷达 + 每日精选精读**的自动化系统，服务于用户（西南大学，裂腹鱼亚科/演化基因组学方向）的文献跟踪与深度阅读：

| 轨 | 主题 | 精读落盘目录（Obsidian 文献精读/） |
|---|---|---|
| A | 裂腹鱼亚科（Schizothoracinae/Schizothorax/Gymnocypris/Schizopygopsis） | 裂腹鱼亚科 |
| B | 演化生物学 / 生信演化分析（多倍体、渐渗、高海拔适应） | 演化生物学 |
| C | 着丝粒生物学（着丝粒演化、卫星 DNA、CENP-A、holocentromere） | 着丝粒生物学 |
| D | 古气候基因组学（古水系、第四纪系统地理、构造抬升与分化） | 古气候基因组学 |
| E | 鲟鱼基因组（Acipenser / Huso / Acipenseridae 基因组组装与比较基因组学） | 鲟鱼基因组 |

数据流：**8 来源检索 → 质量分级看板（GitHub Pages）→ 每日精选 → 全文自动获取 → DeepPaperNote 精读 → Obsidian 笔记 → PDF 同步豆包云盘**

## 2. 关键路径

- 项目根（本仓库）：`/home/wsl/08_work/schizothoracinae-lit-radar`（Windows: `\\wsl.localhost\CJJ\home\wsl\08_work\schizothoracinae-lit-radar`）
- Windows 侧脚本镜像：`D:\lit-radar\scripts\`（WSL 侧 `/mnt/d/lit-radar/scripts/`）—— 与仓库 `scripts/` 保持同步，改动后需 `cp` 回仓库
- 雷达数据：`data/data.json`（fetch.py 产出，GitHub Actions 每日自动跑并推 GitHub，digest 从 GitHub 拉取）
- 每日精选状态：`D:\笔记本\文献阅读\文献阅读\文献精读\文献雷达\.state.json`
- Obsidian 库：`D:\笔记本\文献阅读\文献阅读`（WSL 侧 `/mnt/d/笔记本/文献阅读/文献阅读`），精读笔记在 `文献精读/<领域>/<作者><年>_<主题>.zh-CN/`
- PDF 下载 + 云盘同步目录：`C:\Users\CJJ\files\lit-radar_pdfs`（WSL 侧 `/mnt/c/Users/CJJ/files/lit-radar_pdfs`）—— **必须使用此目录**，lark-cli 白名单限定
- 浏览器下载队列：`deepread_work/browser_download_queue.json`
- 管线中间产物/报告：`deepread_work/`（`*_full_text.md`、`*_bundle.json`、`deepread_report_YYYY-MM-DD.json` 等）

## 3. 每日流水线（Windows 计划任务 `LitRadar_ObsidianDigest`，15:30）

`D:\lit-radar\scripts\run_digest.ps1` 按序执行四步（每步有独立超时与日志，日志在 `D:\lit-radar\logs\digest_log.txt`）：

1. **雷达检索**：`python3 scripts/fetch.py`（WSL）→ 8 来源（OpenAlex / PubMed / Europe PMC / Semantic Scholar / bioRxiv / medRxiv + Unpaywall OA 富集 + PMC XML），更新 `data/data.json`
2. **精选精读预获取**：`python3 scripts/run_deepread.py`（WSL）→ 读当日精选 → `acquire_pdf.py` 自动获取全文
3. **云盘同步**：`lark-cli drive +push --local-dir lit-radar_pdfs --folder-token OTuzf94nAlzW1gdlegQcXgqIn2e --if-exists smart`（PowerShell，先 `Set-Location C:\Users\CJJ\files`）→ 增量同步 PDF 到豆包云盘「文献雷达_PDF」
4. **Obsidian 日报**：`python3 obsidian_digest.py --days 30 --top 5`（Windows Python `C:\Python314\python.exe`）→ 每日精选日报写入 Obsidian

## 4. 全文获取策略（acquire_pdf.py，三级降级）

| 级别 | 通道 | 说明 |
|---|---|---|
| L0 | 元数据补全 | Unpaywall OA 定位 + Europe PMC DOI→PMCID + eLife API（**不要带 `Accept: application/json` 头，会 406**） |
| L1 | 直链 PDF | PLOS / eLife CDN / PMC CDN 等 OA 源直接下载 |
| L2 | PMC 全文 XML | JATS XML（eFetch），~200KB/篇，45 章节 |
| L3 | 浏览器队列 | ScienceDirect / Cell / Nature / Oxford 等防护站 → 写入 `browser_download_queue.json`，由 agent 用浏览器通道下载 |

已实测：PLOS 直链 ✓、eLife 直链 ✓（801KB）、PMC XML ✓、Nature/Oxford 入浏览器队列 ✓。
ScienceDirect API 全文**不可用**（需机构 TDM 授权，403 AUTHENTICATION_ERROR），走浏览器通道。

## 5. 精读标准（硬性约束）

- 精读必须走 **DeepPaperNote 管线**（技能软链接 `/home/wsl/shared-agent-skills/deeppapernote` → `DeepPaperNote/skills/deeppapernote`）
- **格式基准 = Hopkins2026 笔记**（Obsidian `文献精读/演化生物学/Hopkins2026_sex_comb_rate_divergence.zh-CN/`）：证据优先、replication-oriented、含 `*.deeppapernote.json` 与物化图片
- 禁止产出"摘要级骨架"笔记（用户已否决并删除过 10 篇）
- 用户全局规则在 `/home/wsl/.claude/CLAUDE.md`；领域路由在 `DeepPaperNote/skills/deeppapernote/references/domain_rules.yaml`（四领域已配置，全词匹配，同分按字典序）
- 执行顺序不可跳步：configuration → identity → metadata → PDF → extract → admission → figures → bundle → note_plan → draft → lint → quality → readability → Formal Save
- 完成后按领域落盘 Obsidian `文献精读/<领域>/<作者><年>_<主题>.zh-CN/`

## 6. 环境与密钥

- API 密钥：`SCIENTEDIRECT_API_KEY`（项目 `.env`，仅搜索可用）；`OPENALEX_API_KEY`（`~/.bashrc`，`kY02moJrjOx0MzLE3ZTrit`，仅元数据/OA 定位）；Unpaywall 邮箱 `ccj13169@gmail.com`
- DeepPaperNote 配置：`~/.deeppapernote/config.json`（zh-CN / obsidian / vault / 文献精读）
- 豆包云盘：文件夹「文献雷达_PDF」token `OTuzf94nAlzW1gdlegQcXgqIn2e`（`https://my.feishu.cn/drive/folder/OTuzf94nAlzW1gdlegQcXgqIn2e`），容量 100GB（个人版统一配额）
- 执行注意事项：
  - PowerShell 内联 `wsl bash -c` 传复杂命令必坏 → 先 Write `.sh`/`.py` 再 `wsl -d CJJ -- bash <path>` 执行
  - UNC 路径（`\\wsl.localhost\...`）lark-cli 不接受 → 用 `C:\Users\CJJ\files\...`
  - 浏览器下载走 `computer_use_tool(plane="bu")`：navigate → `bu.download(url, filename)`；Cloudflare/POW 站 curl 必失败

## 7. 验收标准

- fetch.py 每日产出 data.json，看板更新（https://2269720613.github.io/schizothoracinae-lit-radar/）
- 每日精选日报在 Obsidian `文献精读/文献雷达/` 下
- 精读笔记 = DeepPaperNote 完整产物（非摘要），含 `.deeppapernote.json` + `images/`
- PDF 全部同步在豆包云盘「文献雷达_PDF」
- 浏览器队列清空或说明剩余项
