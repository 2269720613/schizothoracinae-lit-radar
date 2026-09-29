#!/usr/bin/env python3
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
import xml.etree.ElementTree as ET

# ── Additional literature source APIs ──
EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SEMANTIC_SCHOLAR_BASE = "https://api.semanticscholar.org/graph/v1"
UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
PMC_EFETCH_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
MEDRXIV_API = "https://api.biorxiv.org/details/medrxiv"
UNPAYWALL_EMAIL = "ccj13169@gmail.com"
# Semantic Scholar API key (optional; falls back to shared pool)
SEMANTIC_SCHOLAR_API_KEY = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "").strip() or os.environ.get("S2_API_KEY", "").strip()


ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "data.json"
SOURCE_CACHE_PATH = ROOT / "data" / "openalex_source_cache.json"
KEYWORDS_PATH = ROOT / "config" / "keywords.yaml"
TIERS_PATH = ROOT / "config" / "journal_tiers.yaml"

LOOKBACK_DAYS = 7
BACKFILL_YEARS = 5
BACKFILL_MAX_PER_KEYWORD = 1000
CONTACT_EMAIL = "ccj13169@gmail.com"
SOURCES_BATCH = 50
TRACKS = (("A", "track_a"), ("B", "track_b"), ("C", "track_c"), ("D", "track_d"), ("E", "track_e"))

# The local dev proxy (HTTPS_PROXY=127.0.0.1:10808) fails the TLS handshake
# for *.ncbi.nlm.nih.gov (PubMed/esearch returns "SSL UNEXPECTED_EOF"), and its
# shared exit IP collects OpenAlex 429 rate limits faster than the direct
# connection. Force direct connections for NCBI and OpenAlex hosts; other
# sources (Elsevier/bioRxiv) still go through the proxy. GitHub Actions
# runners have no such proxy, so this is a no-op there.
_NCBI_NO_PROXY = "ncbi.nlm.nih.gov,api.openalex.org"
for _var in ("no_proxy", "NO_PROXY"):
    _cur = os.environ.get(_var, "")
    if _NCBI_NO_PROXY not in _cur:
        os.environ[_var] = (_cur + "," + _NCBI_NO_PROXY).strip(",")

# OpenAlex API key (exported in ~/.bashrc as OPENALEX_API_KEY). Optional; the
# polite pool already uses CONTACT_EMAIL via mailto. When present, append as
# api_key to raise the per-day quota and reduce 429s on daily radar runs.
# Non-interactive shells (Windows scheduled tasks) do not source ~/.bashrc, so
# fall back to parsing it directly.
def _load_openalex_key() -> str:
    val = os.environ.get("OPENALEX_API_KEY", "").strip()
    if val:
        return val
    bashrc = Path.home() / ".bashrc"
    if bashrc.exists():
        try:
            for line in bashrc.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line.startswith("export OPENALEX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return ""


OPENALEX_API_KEY = _load_openalex_key()

# ScienceDirect (Elsevier) API key, read from the project .env.
# NOTE: this key grants metadata/search access only. Full-text (article) and
# PDF endpoints return 403 AUTHENTICATION_ERROR unless the Elsevier account has
# TDM / full-text entitlement enabled in the developer portal.
def _load_sciencedirect_key() -> str:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return ""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SCIENTEDIRECT_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


SCIENTEDIRECT_API_KEY = _load_sciencedirect_key()


def http_get_json(url, retries=3, backoff=2.0, headers=None, fail_fast_429=False):
    headers = {"User-Agent": f"schizothoracinae-lit-radar/1.0 ({CONTACT_EMAIL})"}
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if attempt == retries - 1:
                print(f"WARN: giving up on {url}: HTTP {exc.code}", file=sys.stderr)
                return None
            wait = backoff * (attempt + 1)
            if exc.code == 429:
                retry_after = (exc.headers or {}).get("Retry-After") if exc.headers else None
                # Daily-quota exhaustion (Retry-After of hours) is not worth
                # waiting out inside a fetch run — fail fast and let the next
                # scheduled run pick it up after the reset.
                if retry_after and retry_after.replace(".", "", 1).isdigit() and float(retry_after) > 600:
                    print(f"WARN: daily quota exhausted (Retry-After {retry_after}s), skipping {url}", file=sys.stderr)
                    return None
                # Fail fast for sources whose shared free pool is chronically
                # rate-limited (e.g. Semantic Scholar 429): one 429 means the
                # pool is exhausted for this run, waiting 20s x retries per
                # keyword would stall the whole fetch.
                if fail_fast_429:
                    print(f"WARN: 429 rate-limited (fail-fast), skipping {url}", file=sys.stderr)
                    return None
                # Rate limited: back off hard, honoring Retry-After when sent,
                # so bursts of source-id lookups don't poison the whole run.
                wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else max(wait, 20.0)
            time.sleep(wait)
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


def _openalex_work_to_paper(work, track):
    title = work.get("title") or ""
    if not title:
        return None
    doi = (work.get("doi") or "").replace("https://doi.org/", "").strip().lower()
    # FORMAT_SOURCE: OpenAlex /works response can have
    # primary_location present but primary_location.source == null
    # (e.g. records without an indexed host venue). Verified live via
    # https://api.openalex.org/works?search=Schizothorax&per_page=5&mailto=...
    # on 2026-08-04: several real results returned primary_location
    # as a dict but with source explicitly null in some cases, so
    # `.get("source", {})` is not enough — "source" key can exist
    # with value None, which .get()'s default never catches.
    source = ((work.get("primary_location") or {}).get("source")) or {}
    source_id = (source.get("id") or "").replace("https://openalex.org/", "").strip()
    return {
        "id": doi or work.get("id", ""),
        "title": title,
        "authors": [a["author"]["display_name"] for a in work.get("authorships", [])],
        "journal": source.get("display_name", "") or "",
        "date": work.get("publication_date", ""),
        "doi": doi,
        "url": work.get("id", ""),
        "abstract": reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
        "track": track,
        "source": "OpenAlex",
        "openalex_source_id": source_id,
        "source_type": source.get("type", "") or "",
        "source_is_core": bool(source.get("is_core", False)),
    }


def fetch_openalex(keyword, since_date, track, max_results=50):
    """Cursor-paginated OpenAlex works search. Weekly runs keep the default
    single-page (50) behaviour; backfill passes a larger cap."""
    query = urllib.parse.quote(keyword)
    per_page = 200 if max_results > 50 else 50
    papers = []
    cursor = "*"
    while len(papers) < max_results:
        url = (
            "https://api.openalex.org/works"
            f"?filter=from_publication_date:{since_date},"
            f"type:article,"
            f"title_and_abstract.search:{query}"
            f"&sort=publication_date:desc&per_page={per_page}"
            f"&cursor={urllib.parse.quote(cursor)}&mailto={CONTACT_EMAIL}"
            + (f"&api_key={OPENALEX_API_KEY}" if OPENALEX_API_KEY else "")
        )
        data = http_get_json(url, fail_fast_429=True)
        if not data:
            break
        for work in data.get("results", []):
            paper = _openalex_work_to_paper(work, track)
            if paper:
                papers.append(paper)
        cursor = (data.get("meta") or {}).get("next_cursor") or ""
        if not cursor:
            break
        time.sleep(0.3)
    return papers[:max_results]


def normalize_pubmed_date(pubdate):
    # NOTE: NCBI E-utilities documentation records pubdate as historically
    # inconsistent (e.g. "2021 Dec 23", "2021 Dec", "2021") rather than
    # ISO-8601. This is a high-confidence assumption based on published NCBI
    # docs; it was NOT verified against a live esummary.fcgi response in this
    # session because eutils.ncbi.nlm.nih.gov was unreachable (connection
    # failures / "Socket is closed") from this network environment when
    # checked via curl and WebFetch. Treat as "documented but unverified live"
    # until confirmed against a real response.
    if not pubdate:
        return ""
    pubdate = pubdate.strip()
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%Y %b %d", "%Y %B %d", "%Y %b", "%Y %B"]
    for fmt in formats:
        try:
            dt = datetime.strptime(pubdate, fmt)
            if fmt in ("%Y %b", "%Y %B"):
                return dt.strftime("%Y-%m-01")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    if pubdate.isdigit() and len(pubdate) == 4:
        return f"{pubdate}-01-01"
    return pubdate


def _pubmed_papers_for_pmids(pmids, track):
    """Resolve PMIDs into paper records via esummary, in chunks of 200."""
    papers = []
    for i in range(0, len(pmids), 200):
        chunk = pmids[i:i + 200]
        summary_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
            f"?db=pubmed&id={','.join(chunk)}&retmode=json"
            f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
        )
        summary_data = http_get_json(summary_url)
        time.sleep(0.4)
        if not summary_data:
            continue
        result = summary_data.get("result", {})
        for uid in result.get("uids", []):
            item = result.get(uid, {})
            doi = ""
            for aid in item.get("articleids", []):
                if aid.get("idtype") == "doi":
                    doi = aid.get("value", "").strip().lower()
                    break
            papers.append({
                "id": doi or uid,
                "title": item.get("title", ""),
                "authors": [a.get("name", "") for a in item.get("authors", [])],
                "journal": item.get("fulljournalname", ""),
                "date": normalize_pubmed_date(item.get("pubdate", "")),
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "abstract": "",
                "track": track,
                "source": "PubMed",
            })
    return papers


def fetch_pubmed(keyword, since_date, track, max_results=50):
    """esearch + esummary harvest. Weekly runs keep the single 50-item page;
    backfill pages via retstart up to max_results."""
    term = urllib.parse.quote(f'{keyword} AND ("{since_date}"[PDAT] : "3000"[PDAT])')
    page_size = 200 if max_results > 50 else 50

    def search_url(retstart):
        return (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            f"?db=pubmed&term={term}&retmode=json&retmax={page_size}"
            f"&retstart={retstart}&sort=pub_date"
            f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
        )

    search_data = http_get_json(search_url(0))
    if not search_data:
        return []
    es = search_data.get("esearchresult", {})
    pmids = list(es.get("idlist") or [])
    try:
        count = int(es.get("count") or 0)
    except ValueError:
        count = 0
    start = page_size
    while pmids and len(pmids) < min(count, max_results):
        page_data = http_get_json(search_url(start))
        ids = list((page_data or {}).get("esearchresult", {}).get("idlist") or [])
        if not ids:
            break
        pmids.extend(ids)
        start += page_size
        time.sleep(0.4)
    pmids = pmids[:max_results]
    if not pmids:
        return []
    return _pubmed_papers_for_pmids(pmids, track)


def fetch_biorxiv_recent(keywords, track):
    # bioRxiv's details API only supports fixed day-window buckets (e.g.
    # 10d, 30d), not an arbitrary N-day range, so "10d" here is the closest
    # available option to LOOKBACK_DAYS=7 (not a typo).
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
        doi = (item.get("doi") or "").strip().lower()
        papers.append({
            "id": doi,
            "title": item.get("title", ""),
            "authors": [a.strip() for a in (item.get("authors") or "").split(";") if a.strip()],
            "journal": "bioRxiv (preprint)",
            "date": item.get("date", ""),
            "doi": doi,
            "url": f"https://doi.org/{doi}" if doi else "",
            "abstract": item.get("abstract", ""),
            "track": track,
            "source": "bioRxiv",
        })
    return papers



# ═══════════════════════════════════════════════════════════════════
# Europe PMC — broader than PubMed, includes preprints, OA status, PMCID
# ═══════════════════════════════════════════════════════════════════
def fetch_europepmc(keyword, since_date, track, max_results=50):
    """Search Europe PMC by keyword. Returns unified paper dicts."""
    term = urllib.parse.quote(f'{keyword} AND (FIRST_PDATE:[{since_date} TO 2099-12-31])')
    url = f"{EUROPEPMC_BASE}/search?query={term}&format=json&pageSize={min(max_results, 100)}&resultType=core"
    try:
        data = http_get_json(url)
    except Exception as e:
        print(f"  [europepmc] error for {keyword!r}: {e}", flush=True)
        return []
    results = (data or {}).get("resultList", {}).get("result", [])
    papers = []
    for r in results:
        pmid = r.get("pmid", "")
        pmcid = r.get("pmcid", "")
        doi = r.get("doi", "")
        journal = r.get("journalTitle", "")
        # Extract full-text URLs
        ft_urls = r.get("fullTextUrlList", {}).get("fullTextUrl", [])
        pdf_url = ""
        full_text_url = ""
        for ft in ft_urls:
            u = ft.get("url", "")
            avail = ft.get("availability", "")
            style = ft.get("documentStyle", "")
            if style == "pdf" and avail == "Open access":
                pdf_url = u
            if not full_text_url and u:
                full_text_url = u
        papers.append({
            "title": (r.get("title") or "").strip(),
            "authors": r.get("authorString", ""),
            "journal": journal,
            "date": r.get("firstPublicationDate") or r.get("pubYear", ""),
            "abstract": (r.get("abstractText") or "").strip(),
            "url": f"https://europepmc.org/article/MED/{pmid}" if pmid else (r.get("doi") and f"https://doi.org/{doi}" or ""),
            "doi": doi,
            "pmid": pmid,
            "pmcid": pmcid,
            "is_oa": r.get("isOpenAccess", "N") == "Y",
            "in_pmc": r.get("inPMC", "N") == "Y",
            "pdf_url": pdf_url,
            "full_text_url": full_text_url,
            "source": "europepmc",
            "track": track,
            "cited_by_count": r.get("citedByCount", 0),
        })
    return papers


# ═══════════════════════════════════════════════════════════════════
# Semantic Scholar — citation graph, AI TLDR, broader coverage
# ═══════════════════════════════════════════════════════════════════
def fetch_semantic_scholar(keyword, since_date, track, max_results=50):
    """Search Semantic Scholar by keyword. Returns unified paper dicts."""
    fields = "title,authors,year,abstract,externalIds,url,citationCount,publicationDate,journal,tldr"
    url = f"{SEMANTIC_SCHOLAR_BASE}/paper/search?query={urllib.parse.quote(keyword)}&limit={min(max_results, 100)}&fields={fields}&year={since_date[:4]}-"
    headers = {}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    try:
        data = http_get_json(url, headers=headers, fail_fast_429=True)
    except Exception as e:
        print(f"  [semanticscholar] error for {keyword!r}: {e}", flush=True)
        return []
    results = (data or {}).get("data", [])
    papers = []
    for r in results:
        ext = r.get("externalIds") or {}
        doi = ext.get("DOI", "")
        pmid = ext.get("PubMed", "")
        tldr = (r.get("tldr") or {}).get("text", "")
        authors_list = r.get("authors") or []
        author_str = ", ".join(a.get("name", "") for a in authors_list[:5])
        if len(authors_list) > 5:
            author_str += " et al."
        journal_info = r.get("journal") or {}
        papers.append({
            "title": (r.get("title") or "").strip(),
            "authors": author_str,
            "journal": journal_info.get("name", ""),
            "date": r.get("publicationDate") or str(r.get("year", "")),
            "abstract": (r.get("abstract") or "").strip(),
            "url": r.get("url", ""),
            "doi": doi,
            "pmid": pmid,
            "pmcid": ext.get("PMC", ""),
            "is_oa": None,  # S2 doesn't reliably return OA status
            "in_pmc": bool(ext.get("PMC", "")),
            "pdf_url": "",
            "full_text_url": "",
            "source": "semanticscholar",
            "track": track,
            "cited_by_count": r.get("citationCount", 0),
            "tldr": tldr,
        })
    return papers


# ═══════════════════════════════════════════════════════════════════
# Unpaywall OA enrichment — find PDF direct links for existing papers
# ═══════════════════════════════════════════════════════════════════
def enrich_papers_with_unpaywall(papers, max_dois=50, workers=6):
    """Look up OA status + PDF URL for papers that have a DOI but no pdf_url.
    Mutates papers in place, adding is_oa / oa_status / pdf_url / oa_pdf_source.
    Concurrent worker pool keeps the fetch run within its wall-clock budget."""
    import concurrent.futures as _cf

    def _lookup(p):
        doi = (p.get("doi") or "").strip()
        if not doi or p.get("pdf_url"):
            return None
        url = f"{UNPAYWALL_BASE}/{urllib.parse.quote(doi)}?email={UNPAYWALL_EMAIL}"
        try:
            data = http_get_json(url, fail_fast_429=True)
        except Exception:
            return None
        if not data:
            return None
        out = {"is_oa": data.get("is_oa", False), "oa_status": data.get("oa_status", "closed")}
        if out["is_oa"]:
            best = data.get("best_oa_location") or {}
            pdf = best.get("url_for_pdf") or ""
            if not pdf:
                for loc in data.get("oa_locations") or []:
                    if loc.get("url_for_pdf"):
                        pdf = loc["url_for_pdf"]
                        break
            if pdf:
                out["pdf_url"] = pdf
                out["oa_pdf_source"] = best.get("host_type", "unknown")
        return out

    targets = [p for p in papers if (p.get("doi") or "").strip() and not p.get("pdf_url")][:max_dois]
    if not targets:
        return 0
    enriched = 0
    checked = 0
    with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_lookup, p): p for p in targets}
        for fut in _cf.as_completed(futures):
            p = futures[fut]
            checked += 1
            result = fut.result()
            if result is None:
                continue
            p["is_oa"] = result["is_oa"]
            p["oa_status"] = result["oa_status"]
            if result.get("pdf_url"):
                p["pdf_url"] = result["pdf_url"]
                p["oa_pdf_source"] = result.get("oa_pdf_source", "unknown")
                enriched += 1
            time.sleep(0.05)  # gentle pacing across the pool
    if enriched:
        print(f"  [unpaywall] enriched {enriched}/{checked} papers with OA PDF links", flush=True)
    return enriched


# ═══════════════════════════════════════════════════════════════════
# PMC full-text XML fetcher
# ═══════════════════════════════════════════════════════════════════
def fetch_pmc_fulltext_xml(pmcid, output_path=None):
    """Fetch full-text JATS XML from PMC by PMCID (numeric or PMC-prefixed).
    Returns the XML string, or None on failure. If output_path given, writes there."""
    uid = str(pmcid).replace("PMC", "").strip()
    if not uid:
        return None
    url = f"{PMC_EFETCH_BASE}?db=pmc&id={uid}&retmode=xml"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"schizothoracinae-lit-radar/1.0 ({CONTACT_EMAIL})"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_text = resp.read().decode("utf-8")
        if output_path:
            Path(output_path).write_text(xml_text, encoding="utf-8")
        return xml_text
    except Exception:
        return None


def extract_pmc_body_text(xml_text):
    """Extract plain text from PMC JATS XML body. Returns (body_text, sections_dict)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return "", {}
    ns = {"jats": "http://www.ncbi.nlm.nih.gov/JATS1"}
    body = root.find(".//jats:body", ns)
    if body is None:
        body = root.find(".//body")
    if body is None:
        return "", {}
    full_text = "".join(body.itertext())
    sections = {}
    for sec in body.findall(".//jats:sec", ns) or body.findall(".//sec"):
        title_el = sec.find("jats:title", ns) or sec.find("title")
        title = (title_el.text or "untitled").strip() if title_el is not None else "untitled"
        sec_text = "".join(sec.itertext())
        sections[title] = sec_text
    return full_text.strip(), sections


# ═══════════════════════════════════════════════════════════════════
# medRxiv recent preprints
# ═══════════════════════════════════════════════════════════════════
def fetch_medrxiv_recent(keywords, track, days=LOOKBACK_DAYS):
    """Fetch recent medRxiv preprints matching keywords."""
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"{MEDRXIV_API}/{start}/{end}/0"
    try:
        data = http_get_json(url)
    except Exception:
        return []
    collection = (data or {}).get("collection", [])
    kw_lower = [k.lower() for k in keywords]
    papers = []
    for r in collection:
        title = (r.get("title") or "").lower()
        abstract = (r.get("abstract") or "").lower()
        if not any(kw in title or kw in abstract for kw in kw_lower):
            continue
        doi = r.get("doi", "")
        papers.append({
            "title": (r.get("title") or "").strip(),
            "authors": r.get("authors", ""),
            "journal": "medRxiv",
            "date": r.get("date", ""),
            "abstract": (r.get("abstract") or "").strip(),
            "url": f"https://doi.org/{doi}" if doi else "",
            "doi": doi,
            "pmid": "",
            "pmcid": "",
            "is_oa": True,
            "in_pmc": False,
            "pdf_url": f"https://www.medrxiv.org/content/{doi}v1.full.pdf" if doi else "",
            "full_text_url": f"https://doi.org/{doi}" if doi else "",
            "source": "medrxiv",
            "track": track,
            "cited_by_count": 0,
        })
    return papers


def load_tiers_config(path=TIERS_PATH):
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    top = {normalize_journal_name(n) for n in (cfg.get("whitelist_top") or []) if n}
    fish = {normalize_journal_name(n) for n in (cfg.get("whitelist_fish") or []) if n}
    thresholds = cfg.get("thresholds") or {}
    noise = [p.lower() for p in (cfg.get("noise_title_patterns") or [])]
    exclude = [p.lower() for p in (cfg.get("exclude_title_patterns") or [])]
    fish_patterns = [p.lower() for p in (cfg.get("fish_title_patterns") or [])]
    return {
        "whitelist_top": top,
        "whitelist_fish": fish,
        "fish_title_patterns": fish_patterns,
        "min_h_index": thresholds.get("min_h_index", 0),
        "min_2yr_mean_citedness": thresholds.get("min_2yr_mean_citedness", 0),
        "noise_title_patterns": noise,
        "exclude_title_patterns": exclude,
        "min_tier": int(cfg.get("min_tier", 3)),
    }


def normalize_journal_name(name):
    if not name:
        return ""
    out = []
    for ch in name.lower():
        out.append(ch if ch.isalnum() or ch in " &" else " ")
    return " ".join("".join(out).split())


def fetch_source_metrics_batch(source_ids):
    """Query OpenAlex Sources API for a batch of S-ids (max 50). Returns {sid: metrics}."""
    if not source_ids:
        return {}
    id_filter = "|".join(source_ids)
    url = (
        "https://api.openalex.org/sources"
        f"?filter=ids.openalex:{urllib.parse.quote(id_filter, safe='|')}"
        f"&select=id,summary_stats,is_core,type&per_page=50&mailto={CONTACT_EMAIL}"
    )
    data = http_get_json(url)
    out = {}
    if not data:
        return out
    for src in data.get("results", []):
        sid = (src.get("id") or "").replace("https://openalex.org/", "").strip()
        if not sid:
            continue
        stats = src.get("summary_stats") or {}
        out[sid] = {
            "h_index": stats.get("h_index"),
            "citedness": stats.get("2yr_mean_citedness"),
            "is_core": bool(src.get("is_core", False)),
            "type": src.get("type", "") or "",
        }
    return out


def enrich_source_metrics(papers):
    """Collect unique OpenAlex source ids across papers and batch-resolve their metrics."""
    sids = sorted({p.get("openalex_source_id") for p in papers if p.get("openalex_source_id")})
    metrics = {}
    for i in range(0, len(sids), SOURCES_BATCH):
        metrics.update(fetch_source_metrics_batch(sids[i:i + SOURCES_BATCH]))
        time.sleep(0.3)
    return metrics


def is_fish_paper(paper, cfg):
    """Track A is fish by definition; other tracks match word-start anchored
    title patterns (\bfish matches fish/fishes/fishery). Word-start anchoring
    can over-match rare stems (e.g. \bcarp in Carpathian) — accepted, since a
    false positive only relaxes the venue bar, never hides a paper."""
    if paper.get("track") == "A":
        return True
    title_l = (paper.get("title") or "").lower()
    return any(re.search(rf"\b{re.escape(pat)}", title_l) for pat in cfg["fish_title_patterns"])


def assign_tier(paper, metrics, cfg):
    title_l = (paper.get("title") or "").lower()
    jname = normalize_journal_name(paper.get("journal") or "")

    sid = paper.get("openalex_source_id")
    m = metrics.get(sid) if sid else None
    h_index = (m or {}).get("h_index")
    citedness = (m or {}).get("citedness")
    paper["journal_h_index"] = h_index
    paper["journal_citedness"] = citedness

    # Topic exclusions (e.g. stress experiments) win over everything,
    # including whitelist venues and bioRxiv preprints.
    if any(pat in title_l for pat in cfg["exclude_title_patterns"]):
        paper["tier"] = 0
        return

    fish = is_fish_paper(paper, cfg)
    paper["is_fish"] = fish

    # Dual standard: fish papers may pass via the relaxed one/two-tier route
    # (fish whitelist or OpenAlex metrics); non-fish papers need a top journal.
    if paper.get("source") == "bioRxiv":
        tier = 2 if fish else 3
    elif jname in cfg["whitelist_top"]:
        tier = 1
    elif fish and jname in cfg["whitelist_fish"]:
        tier = 1
    elif any(pat in title_l for pat in cfg["noise_title_patterns"]):
        tier = 0
    elif (
        fish
        and m
        and m.get("type") == "journal"
        and m.get("is_core")
        and ((h_index is not None and h_index >= cfg["min_h_index"])
             or (citedness is not None and citedness >= cfg["min_2yr_mean_citedness"]))
    ):
        tier = 2
    elif jname:
        tier = 3
    else:
        tier = 0

    paper["tier"] = tier
    if tier > cfg["min_tier"]:
        paper["tier"] = 0


def tier_papers(papers, cfg):
    """Enrich journal metrics and stamp a tier on every paper object passed in."""
    metrics = enrich_source_metrics(papers)
    for p in papers:
        assign_tier(p, metrics, cfg)


def load_source_cache():
    if SOURCE_CACHE_PATH.exists():
        try:
            return json.loads(SOURCE_CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_source_cache(cache):
    SOURCE_CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )


def lookup_openalex_source_id(journal, cache):
    # PubMed-style names carry NLM qualifiers ("Aquaculture (Amsterdam,
    # Netherlands)") that OpenAlex display names don't have; strip any
    # trailing parenthetical before searching.
    base = re.sub(r"\s*\([^)]*\)\s*$", "", journal.strip()).strip()
    while "(" in base and base.endswith(")"):
        base = re.sub(r"\s*\([^)]*\)\s*$", "", base).strip()
    jn = normalize_journal_name(base)
    if not jn or jn == "biorxiv preprint":
        return None
    if jn in cache:
        return cache[jn]
    query = urllib.parse.quote(f'"{base}"')
    url = (
        "https://api.openalex.org/sources"
        f"?filter=display_name.search:{query}"
        f"&select=id,display_name,type&per_page=10&mailto={CONTACT_EMAIL}"
    )
    data = http_get_json(url)
    if data is None:
        # Network failure / rate limit: do NOT negative-cache, or the journal
        # would be skipped forever instead of retried on the next run.
        return None
    sid = None
    for src in data.get("results", []):
        if (src.get("type") or "") != "journal":
            continue
        rname = normalize_journal_name(src.get("display_name") or "")
        # Exact normalized match first; fall back to prefix match for
        # indexed names carrying extra qualifiers.
        if rname == jn or (len(jn) >= 8 and rname.startswith(jn)):
            sid = (src.get("id") or "").replace("https://openalex.org/", "").strip() or None
            break
    # Cache misses too (null): repositories/preprint servers stay unresolved,
    # so later runs skip re-querying them and stop wasting rate limit.
    cache[jn] = sid
    time.sleep(1.0)
    return sid


def resolve_missing_source_ids(papers, cache=None, checkpoint=False, max_lookups=0):
    """Fill openalex_source_id for papers missing one by matching their journal
    display_name against the OpenAlex Sources API. Only legacy records and
    PubMed hits miss the id; resolving them lets metric-based T2 tiering apply.
    Concurrent lookups keep the whole run inside its wall-clock budget.
    max_lookups>0 caps daily journal lookups so backfill cannot exhaust the
    OpenAlex free quota (100k/day shared); results persist to the source cache."""
    import concurrent.futures as _cf
    cache = cache if cache is not None else {}
    targets = [
        p for p in papers
        if not p.get("openalex_source_id") and (p.get("journal") or "").strip()
    ]
    if max_lookups > 0:
        targets = targets[:max_lookups]
    resolved = 0

    def _resolve(p):
        sid = lookup_openalex_source_id(p["journal"], cache)
        return p, sid

    with _cf.ThreadPoolExecutor(max_workers=5) as ex:
        futures = [ex.submit(_resolve, p) for p in targets]
        for i, fut in enumerate(_cf.as_completed(futures), 1):
            p, sid = fut.result()
            if sid:
                p["openalex_source_id"] = sid
                resolved += 1
            if checkpoint and i % 50 == 0:
                print(f"source-id backfill: {i}/{len(targets)} journals queried, {resolved} ids filled",
                      flush=True)
                save_source_cache(cache)
    if checkpoint and targets:
        print(f"source-id backfill: {len(targets)} journals queried, {resolved} ids filled (final)",
              flush=True)
        save_source_cache(cache)
    return resolved


def merge_papers(existing_papers, new_papers):
    by_id = {(p.get("id") or p.get("title", "").lower()): p for p in existing_papers}
    added = 0
    for p in new_papers:
        key = p.get("id") or p.get("title", "").lower()
        if key and key not in by_id:
            by_id[key] = p
            added += 1
    merged = sorted(by_id.values(), key=lambda p: p.get("date", ""), reverse=True)
    return merged, added


def dedupe_papers(papers):
    """Unique by id/title, keeping first occurrence. Duplicates are distinct dict
    objects when the same paper is collected into more than one track."""
    seen_ids = set()
    out = []
    for p in papers:
        key = p.get("id") or p.get("title", "").lower()
        if key not in seen_ids:
            seen_ids.add(key)
            out.append(p)
    return out


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
        trend.append({"week": week_start.strftime("%G-W%V"), "count": count})
    tier_counts = {"1": 0, "2": 0, "3": 0, "0": 0}
    for p in all_papers:
        t = str(p.get("tier", 3))
        tier_counts[t] = tier_counts.get(t, 0) + 1
    return {
        "total_count": total,
        "new_this_week": new_this_week,
        "weekly_trend": trend,
        "tier_counts": tier_counts,
    }


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {
        "generated_at": "",
        "tracks": {
            track_id: {"label": "", "keywords": [], "papers": []}
            for track_id, _ in TRACKS
        },
        "stats": {"total_count": 0, "new_this_week": 0, "weekly_trend": [], "tier_counts": {}},
    }


def main():
    backfill = "--backfill" in sys.argv
    skip_backfill = "--skip-backfill" in sys.argv
    now = datetime.now(timezone.utc)
    if backfill:
        since_date = (now - timedelta(days=365 * BACKFILL_YEARS)).date().isoformat()
        max_results = BACKFILL_MAX_PER_KEYWORD
        print(f"backfill mode: since {since_date}, cap {max_results} per keyword", flush=True)
    else:
        since_date = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
        max_results = 50
    if skip_backfill:
        print("skip-backfill mode: source-id journal lookups disabled this run", flush=True)
    config = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))
    tiers_cfg = load_tiers_config()
    existing = load_existing()
    total_added = 0

    for track_id, cfg_key in TRACKS:
        track_cfg = config[cfg_key]
        track_state = existing["tracks"].setdefault(
            track_id, {"label": "", "keywords": [], "papers": []}
        )
        track_state["label"] = track_cfg["label"]
        track_state["keywords"] = track_cfg["keywords"]

        new_papers = []
        for kw in track_cfg["keywords"]:
            oa = fetch_openalex(kw, since_date, track_id, max_results=max_results)
            time.sleep(0.2)
            pm = fetch_pubmed(kw, since_date, track_id, max_results=max_results)
            time.sleep(0.4)
            epmc = fetch_europepmc(kw, since_date, track_id, max_results=max_results)
            time.sleep(0.3)
            s2 = fetch_semantic_scholar(kw, since_date, track_id, max_results=max_results)
            time.sleep(1.0)  # S2 shared pool is rate-limited
            new_papers.extend(oa)
            new_papers.extend(pm)
            new_papers.extend(epmc)
            new_papers.extend(s2)
            if backfill:
                print(f"  {track_id} {kw}: openalex={len(oa)} pubmed={len(pm)} europepmc={len(epmc)} s2={len(s2)}", flush=True)

        new_papers.extend(fetch_biorxiv_recent(track_cfg["keywords"], track_id))
        new_papers.extend(fetch_medrxiv_recent(track_cfg["keywords"], track_id))
        # Enrich OA PDF links via Unpaywall for papers missing pdf_url
        enrich_papers_with_unpaywall(new_papers, max_dois=80)

        merged, added = merge_papers(track_state["papers"], new_papers)
        track_state["papers"] = merged
        total_added += added

    tracked_papers = [p for tid, _ in TRACKS for p in existing["tracks"][tid]["papers"]]
    all_papers = dedupe_papers(tracked_papers)

    source_cache = load_source_cache()
    if skip_backfill:
        resolved = 0
    else:
        # Cap daily journal backfill to 400 lookups: enough to converge the
        # cache over time without burning the OpenAlex free quota (100k/day).
        resolved = resolve_missing_source_ids(
            tracked_papers, source_cache, checkpoint=True, max_lookups=400
        )
    if resolved:
        print(f"resolved {resolved} missing OpenAlex source ids via journal-name lookup")
    save_source_cache(source_cache)

    # Re-stamp tier for every paper each run so whitelist/threshold edits apply
    # retroactively to already-collected papers. Runs over tracked_papers, not the
    # deduped subset: a paper collected into two tracks is two separate dicts.
    tier_papers(tracked_papers, tiers_cfg)

    existing["stats"] = compute_stats(all_papers, now)
    existing["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    tc = existing["stats"]["tier_counts"]
    print(
        f"fetch.py done: +{total_added} new papers, total={len(all_papers)}, "
        f"tiers(1/2/3/noise)={tc.get('1')}/{tc.get('2')}/{tc.get('3')}/{tc.get('0')}"
    )


if __name__ == "__main__":
    main()
