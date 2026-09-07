# 文献雷达 × 精选精读工作流（WORKFLOW.md）

> 本文件是整套系统的人类/Agent 双读文档。任何 Agent 接入请先读 `AGENTS.md`（根目录），
> 然后跑 `python3 scripts/env_check.py` 自检。

## 系统全景

```
┌─────────────────────────────────────────────────────────────────┐
│  每日 15:30  Windows 计划任务 LitRadar_ObsidianDigest           │
│  run_digest.ps1（D:\lit-radar\scripts\）                        │
│                                                                 │
│  ① fetch.py ──→ 8 来源检索（OpenAlex/PubMed/EuropePMC/SS/       │
│                  bioRxiv/medRxiv + Unpaywall + PMC XML）         │
│  ② run_deepread.py ──→ 精选 → acquire_pdf.py 三级降级获取全文   │
│  ③ lark-cli drive +push ──→ PDF 增量同步豆包云盘「文献雷达_PDF」 │
│  ④ obsidian_digest.py ──→ 每日精选日报写入 Obsidian             │
└─────────────────────────────────────────────────────────────────┘
        │                                  │
        ▼                                  ▼
   GitHub Pages 看板               Obsidian 文献精读/<领域>/
   （GitHub Actions 每日跑）        Hopkins2026 格式精读笔记
```

## 每日闭环

| 环节 | 谁执行 | 何时 | 产物 |
|---|---|---|---|
| 雷达检索 | fetch.py（GitHub Actions 每日 + 本地计划任务） | 每日 | `data/data.json`、GitHub Pages 看板 |
| 每日精选 | obsidian_digest.py（计划任务） | 15:30 后 | Obsidian `文献精读/文献雷达/` 日报 + `.state.json` |
| 全文预获取 | run_deepread.py（计划任务） | 15:30 后 | PDF → 云盘同步目录；PMC XML；浏览器队列 |
| 云盘备份 | lark-cli drive +push | 15:30 后 | 豆包云盘「文献雷达_PDF」 |
| 深度精读 | Agent（豆包/Claude Code 手动触发） | 日报后 | Hopkins2026 格式笔记 + `.deeppapernote.json` + images/ |

## 全文获取三级降级

1. **L1 直链 PDF**：Unpaywall/eLife API 定位 OA 直链 → curl 下载（PLOS/eLife/PMC CDN 均实测可用）
2. **L2 PMC 全文 XML**：Europe PMC eFetch → JATS XML → 提取正文（~45 章节）
3. **L3 浏览器队列**：ScienceDirect/Cell/Nature/Oxford 等 → `browser_download_queue.json` → Agent 用浏览器通道下载

## 精读标准（与 Hopkins2026 完全一致）

- 必须走 DeepPaperNote 管线 17 步（不可跳步）：configuration → identity → metadata → PDF → extract → admission → figures → bundle → note_plan → draft → lint → quality → readability → Formal Save
- 证据优先：每条核心结论必须挂 `supporting_evidence` 且通过 lint_grounding
- 图片必须物化到笔记 `images/` 目录，figure insert 需 `visual_review` 契约
- 落盘：`文献精读/<领域>/<作者><年>_<主题>.zh-CN/`（`.md` + `.deeppapernote.json` + `images/`）

## 关键约束（踩坑记录）

| 坑 | 正确姿势 |
|---|---|
| PowerShell 内联 `wsl bash -c` 复杂命令必坏 | Write `.sh`/`.py` → `wsl -d CJJ -- bash <path>` |
| lark-cli 不接受 UNC 路径 | 用 `C:\Users\CJJ\files\...`（白名单根） |
| `Accept: application/json` 调 eLife API → 406 | 去掉 Accept 头 |
| ScienceDirect API 全文 → 403 | 需机构 TDM 授权，走浏览器通道 |
| science.org / PMC 网页 PDF curl → Cloudflare | 浏览器通道 `bu.download()` |
| 精读自动路由误判 | domain_rules.yaml 全词匹配，强判别词放 aliases ×80 |
