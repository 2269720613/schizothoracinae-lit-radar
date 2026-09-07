#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF / 全文自动获取模块 — 增强版三级降级

对一篇精选论文，按优先级尝试获取全文：
  0. 有 DOI → 查 Unpaywall 找 OA PDF 直链；查 Europe PMC 把 DOI 转 PMCID
  1. pdf_url 直链下载（Unpaywall / 出版社 OA / 预印本）
  2. PMCID → PMC eFetch 全文 XML（JATS，可直接供 DeepPaperNote 使用）
  3. 浏览器通道（受 Cloudflare/权限防护的 ScienceDirect / Cell / Nature / science.org）
     —— 生成浏览器下载任务队列

输出：
  - 成功：{"status": "ok", "path": "...", "method": "direct|pmc_xml"}
  - 需浏览器：{"status": "need_browser", "url": "...", "slug": "..."}
  - 失败：{"status": "failed", "reason": "..."}
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────
DEEPREAD_ROOT = Path("/home/wsl/08_work/schizothoracinae-lit-radar/deepread_work")
# PDF 下载目录 = Windows 云盘同步目录（lark-cli 白名单内，push 到豆包云盘）
PDF_DIR = Path("/mnt/c/Users/CJJ/files/lit-radar_pdfs")
BROWSER_QUEUE = DEEPREAD_ROOT / "browser_download_queue.json"
CONTACT_EMAIL = "ccj13169@gmail.com"
USER_AGENT = f"schizothoracinae-lit-radar/1.0 ({CONTACT_EMAIL})"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# 需要浏览器通道的域名模式（curl 直下会被 Cloudflare/POW 拦截）
BROWSER_ONLY_DOMAINS = [
    "sciencedirect.com",
    "cell.com",
    "science.org",
    "nature.com",
    "springer.com",
    "wiley.com",
    "online.ucpress.edu",
    "pnas.org",
    "academic.oup.com",
    "tandfonline.com",
]


def http_get_json(url, timeout=30):
    """GET JSON，带重试"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < 2:
                time.sleep(1)
                continue
            return None
    return None


def http_download(url, out_path, timeout=60):
    """直链下载，返回 (success, size_or_error)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 1000:
            head = data[:200].decode("utf-8", errors="replace").lower()
            if "<html" in head or "error" in head or "cloudflare" in head or "captcha" in head:
                return False, f"response looks like HTML/error ({len(data)} bytes)"
        # 检查 PDF 魔数
        if data[:4] != b"%PDF":
            return False, f"not a PDF (magic={data[:4]!r})"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return True, len(data)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def needs_browser(url):
    if not url:
        return False
    url_lower = url.lower()
    return any(domain in url_lower for domain in BROWSER_ONLY_DOMAINS)


def lookup_unpaywall(doi):
    """查 Unpaywall 拿 OA 状态 + PDF 直链"""
    if not doi:
        return None
    url = f"{UNPAYWALL_BASE}/{urllib.parse.quote(doi)}?email={CONTACT_EMAIL}"
    data = http_get_json(url)
    if not data:
        return None
    result = {
        "is_oa": data.get("is_oa", False),
        "oa_status": data.get("oa_status", "closed"),
    }
    best = data.get("best_oa_location") or {}
    result["pdf_url"] = best.get("url_for_pdf") or ""
    if not result["pdf_url"]:
        for loc in data.get("oa_locations") or []:
            if loc.get("url_for_pdf"):
                result["pdf_url"] = loc["url_for_pdf"]
                result["pdf_host"] = loc.get("host_type", "unknown")
                break
    result["landing_url"] = best.get("url_for_landing_page") or ""
    return result


def lookup_pmcid_via_europepmc(doi):
    """通过 Europe PMC 把 DOI 转 PMCID"""
    if not doi:
        return ""
    url = f"{EUROPEPMC_BASE}/search?query=DOI:{urllib.parse.quote(doi)}&format=json&pageSize=1"
    data = http_get_json(url)
    if not data:
        return ""
    results = data.get("resultList", {}).get("result", [])
    if results:
        return results[0].get("pmcid", "")
    return ""


def lookup_elife_pdf(doi):
    """eLife 专属：DOI 10.7554/elife.{id} → api.elifesciences.org 拿 PDF 直链"""
    import re
    m = re.match(r"10\.7554/eLife\.(\d+)", doi, re.IGNORECASE)
    if not m:
        return ""
    article_id = m.group(1)
    url = f"https://api.elifesciences.org/articles/{article_id}"
    # eLife API 对 Accept: application/json 返回 406，需要无 Accept 头请求
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("pdf", "")
    except Exception:
        return ""


def fetch_pmc_fulltext_xml(pmcid, out_path):
    uid = str(pmcid).replace("PMC", "").strip()
    if not uid:
        return False, "invalid PMCID"
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={uid}&retmode=xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_text = resp.read().decode("utf-8")
        if len(xml_text) < 500 or "<html" in xml_text[:200].lower():
            return False, "PMC response too short or HTML"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(xml_text, encoding="utf-8")
        return True, len(xml_text)
    except Exception as e:
        return False, str(e)


def enqueue_browser(slug, browser_url, doi="", pmcid="", title=""):
    """加入浏览器下载队列"""
    queue = []
    if BROWSER_QUEUE.exists():
        try:
            queue = json.loads(BROWSER_QUEUE.read_text(encoding="utf-8"))
        except Exception:
            queue = []
    if not any(q.get("slug") == slug for q in queue):
        queue.append({
            "slug": slug,
            "url": browser_url,
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "added_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "pending",
        })
        BROWSER_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        BROWSER_QUEUE.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    return False


def acquire(paper, out_dir=None):
    """
    paper: dict with keys: doi, pmcid, pdf_url, url, title, slug
    返回 dict: {status, path, method, reason, browser_url}
    """
    out_dir = Path(out_dir) if out_dir else PDF_DIR
    slug = paper.get("slug") or "paper"
    doi = paper.get("doi", "").strip()
    pmcid = paper.get("pmcid", "").strip()
    pdf_url = paper.get("pdf_url", "").strip()
    url = paper.get("url", "").strip()

    # ── Level 0: 元数据补全（Unpaywall OA 定位 + Europe PMC DOI→PMCID + eLife API） ──
    if doi:
        unpay = lookup_unpaywall(doi)
        if unpay and unpay.get("pdf_url") and not pdf_url:
            pdf_url = unpay["pdf_url"]
            print(f"    [unpaywall] OA PDF 直链: {pdf_url[:90]}", flush=True)
        if not pmcid:
            found = lookup_pmcid_via_europepmc(doi)
            if found:
                pmcid = found
                print(f"    [europepmc] DOI→PMCID: {pmcid}", flush=True)
        if not pdf_url:
            elife_pdf = lookup_elife_pdf(doi)
            if elife_pdf:
                pdf_url = elife_pdf
                print(f"    [elife] PDF 直链: {pdf_url[:90]}", flush=True)

    # ── Level 1: 直链 PDF 下载 ──
    if pdf_url:
        pdf_path = out_dir / f"{slug}.pdf"
        if pdf_path.exists() and pdf_path.stat().st_size > 10000:
            return {"status": "ok", "path": str(pdf_path), "method": "direct_cached"}
        # 浏览器专属域名 → 直接排队浏览器
        if needs_browser(pdf_url):
            enqueue_browser(slug, pdf_url, doi, pmcid, paper.get("title", ""))
            return {"status": "need_browser", "browser_url": pdf_url, "slug": slug}
        ok, info = http_download(pdf_url, pdf_path)
        if ok:
            print(f"  [direct] PDF downloaded: {pdf_path} ({info} bytes)", flush=True)
            return {"status": "ok", "path": str(pdf_path), "method": "direct"}
        print(f"  [direct] failed: {info}", flush=True)

    # ── Level 2: PMC 全文 XML ──
    if pmcid:
        xml_path = out_dir / f"{slug}.xml"
        if xml_path.exists() and xml_path.stat().st_size > 500:
            return {"status": "ok", "path": str(xml_path), "method": "pmc_xml_cached"}
        ok, info = fetch_pmc_fulltext_xml(pmcid, xml_path)
        if ok:
            print(f"  [pmc_xml] full-text XML: {xml_path} ({info} chars)", flush=True)
            return {"status": "ok", "path": str(xml_path), "method": "pmc_xml"}
        print(f"  [pmc_xml] failed: {info}", flush=True)

    # ── Level 3: 浏览器通道 ──
    browser_url = pdf_url or url or (f"https://doi.org/{doi}" if doi else "")
    if browser_url and needs_browser(browser_url):
        enqueue_browser(slug, browser_url, doi, pmcid, paper.get("title", ""))
        print(f"  [browser] queued: {browser_url}", flush=True)
        return {"status": "need_browser", "browser_url": browser_url, "slug": slug}

    # ── Level 4: 尝试 landing page 直链（PLOS / eLife / PMC 等 OA 站） ──
    if url and not needs_browser(url):
        pdf_path = out_dir / f"{slug}.pdf"
        ok, info = http_download(url, pdf_path)
        if ok:
            return {"status": "ok", "path": str(pdf_path), "method": "direct_landing"}
        print(f"  [direct_landing] failed: {info}", flush=True)

    return {"status": "failed", "reason": "no available acquisition method", "doi": doi, "url": url}


def acquire_batch(papers, out_dir=None):
    results = []
    for p in papers:
        slug = p.get("slug", "unknown")
        print(f"Acquiring: {slug} (doi={p.get('doi','')}, pmcid={p.get('pmcid','')})", flush=True)
        result = acquire(p, out_dir)
        result["slug"] = slug
        results.append(result)
    return results


def main():
    ap = argparse.ArgumentParser(description="PDF/全文自动获取")
    ap.add_argument("--doi", default="")
    ap.add_argument("--pmcid", default="")
    ap.add_argument("--pdf-url", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--slug", default="paper")
    ap.add_argument("--title", default="")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--batch-json", default="", help="批量模式：JSON 文件路径")
    args = ap.parse_args()

    if args.batch_json:
        papers = json.loads(Path(args.batch_json).read_text(encoding="utf-8"))
        results = acquire_batch(papers, args.out_dir or None)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        paper = {
            "doi": args.doi,
            "pmcid": args.pmcid,
            "pdf_url": args.pdf_url,
            "url": args.url,
            "slug": args.slug,
            "title": args.title,
        }
        result = acquire(paper, args.out_dir or None)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
