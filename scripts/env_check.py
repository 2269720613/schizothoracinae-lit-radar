#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献雷达工作流环境自检 — 任何新 Agent 接入时先运行:
    python3 scripts/env_check.py
输出 PASS/WARN/FAIL 清单与修复提示。"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path("/home/wsl/08_work/schizothoracinae-lit-radar")
WARN = "WARN"; PASS = "PASS"; FAIL = "FAIL"
results = []

def check(name, ok, hint=""):
    status = PASS if ok else FAIL
    results.append((status, name, hint))
    return ok

def warn(name, hint=""):
    results.append((WARN, name, hint))

# ── 1. 基础环境 ────────────────────────────────────────────────
check("Python3 可用", shutil.which("python3") is not None)
try:
    py_ver = subprocess.run(["python3", "--version"], capture_output=True, text=True, timeout=15).stdout.strip()
    check(f"Python3 版本: {py_ver}", bool(py_ver))
except Exception as e:
    check("Python3 版本", False, str(e))

# ── 2. 项目结构 ────────────────────────────────────────────────
for name in ["scripts/fetch.py", "scripts/acquire_pdf.py", "scripts/run_deepread.py",
             "scripts/obsidian_digest.py", "config/keywords.yaml", "config/journal_tiers.yaml",
             "data/data.json", "AGENTS.md"]:
    check(f"项目文件 {name}", (ROOT / name).exists(), f"缺少 {name}")

# ── 3. DeepPaperNote 技能链 ────────────────────────────────────
dpp = pathlib.Path("/home/wsl/shared-agent-skills/deeppapernote")
check("DeepPaperNote 技能软链接", dpp.is_symlink() or dpp.exists(), "ln -s DeepPaperNote/skills/deeppapernote ~/shared-agent-skills/deeppapernote")
if check("run_pipeline.py", (dpp / "scripts/run_pipeline.py").exists(), "技能目录不完整"):
    check("write_obsidian_note.py", (dpp / "scripts/write_obsidian_note.py").exists())
    check("lint_grounding.py / lint_note.py", (dpp / "scripts/lint_grounding.py").exists() and (dpp / "scripts/lint_note.py").exists())

cfg = pathlib.Path.home() / ".deeppapernote/config.json"
if check("~/.deeppapernote/config.json", cfg.exists(), "需运行技能 user_configuration.py 生成"):
    try:
        c = json.loads(cfg.read_text(encoding="utf-8"))
        check("配置 output_language=zh-CN", str(c.get("output_language", "")) == "zh-CN", f"当前: {c.get('output_language')}")
        check("配置 save_mode=obsidian", str(c.get("save_mode", "")) == "obsidian", f"当前: {c.get('save_mode')}")
    except Exception as e:
        warn("config.json 解析", str(e))

dom = pathlib.Path("/home/wsl/shared-agent-skills/DeepPaperNote/skills/deeppapernote/references/domain_rules.yaml")
if dom.exists():
    text = dom.read_text(encoding="utf-8-sig")
    for label in ["裂腹鱼", "演化生物学", "着丝粒", "古气候"]:
        check(f"领域路由含 {label}", label in text)
else:
    check("domain_rules.yaml", False)

# ── 4. 云盘 / 同步目录 ─────────────────────────────────────────
cloud = pathlib.Path("/mnt/c/Users/CJJ/files/lit-radar_pdfs")
check("云盘同步目录 C:\\Users\\CJJ\\files\\lit-radar_pdfs", cloud.exists(), "mkdir C:\\Users\\CJJ\\files\\lit-radar_pdfs")

# ── 5. 队列 / 工作目录 ─────────────────────────────────────────
check("deepread_work/ 存在", (ROOT / "deepread_work").exists())
q = ROOT / "deepread_work/browser_download_queue.json"
if q.exists():
    try:
        items = json.loads(q.read_text(encoding="utf-8"))
        pending = [i for i in items if isinstance(i, dict) and i.get("status") == "pending"]
        warn(f"浏览器下载队列 {len(pending)} 条待处理", "agent 需浏览器通道处理" if pending else "")
    except Exception:
        warn("browser_download_queue.json 解析失败")

# ── 6. Obsidian 库 ─────────────────────────────────────────────
vault = pathlib.Path("/mnt/d/笔记本/文献阅读/文献阅读")
check("Obsidian 库存在", vault.exists())
hopkins = vault / "文献精读/演化生物学/Hopkins2026_sex_comb_rate_divergence.zh-CN"
check("Hopkins2026 基准笔记存在", hopkins.exists(), "格式基准，勿删")

# ── 7. Windows 侧（仅 WARN，WSL 内无法强校验）──────────────────
warn("lark-cli（Windows 侧）", "PowerShell: lark-cli drive --help")
warn("计划任务 LitRadar_ObsidianDigest", "PowerShell: schtasks /query /tn LitRadar_ObsidianDigest")
warn("run_digest.ps1 四步流水线", "D:\\lit-radar\\scripts\\run_digest.ps1")
warn("API 密钥", "SCIENTEDIRECT_API_KEY 在 .env；OPENALEX_API_KEY 在 ~/.bashrc")

# ── 汇总 ───────────────────────────────────────────────────────
print()
print("=" * 64)
print("文献雷达工作流环境自检结果")
print("=" * 64)
for status, name, hint in results:
    flag = {"PASS": "  ✅", "WARN": "  ⚠️", "FAIL": "  ❌"}[status]
    line = f"{flag} [{status}] {name}"
    if hint and status != PASS:
        line += f"\n      → {hint}"
    print(line)
n_pass = sum(1 for r in results if r[0] == PASS)
n_warn = sum(1 for r in results if r[0] == WARN)
n_fail = sum(1 for r in results if r[0] == FAIL)
print("-" * 64)
print(f"PASS: {n_pass}   WARN: {n_warn}   FAIL: {n_fail}")
if n_fail:
    print("存在 FAIL 项，按提示修复后再开始工作流。")
else:
    print("核心环境就绪，可执行每日流水线或精读任务。")
