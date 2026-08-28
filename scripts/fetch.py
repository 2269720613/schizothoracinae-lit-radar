#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "data.json"
KEYWORDS_PATH = ROOT / "config" / "keywords.yaml"
TIERS_PATH = ROOT / "config" / "journal_tiers.yaml"

LOOKBACK_DAYS = 7
CONTACT_EMAIL = "ccj13169@gmail.com"
SOURCES_BATCH = 50

# The local dev proxy (HTTPS_PROXY=127.0.0.1:10808) fails the TLS handshake
# for *.ncbi.nlm.nih.gov (PubMed/esearch returns "SSL UNEXPECTED_EOF"), while
# NCBI is reachable directly. Force direct connections for NCBI hosts; other
# sources (OpenAlex/Elsevier/bioRxiv) still go through the proxy. GitHub
# Actions runners have no such proxy, so this is a no-op there.
_NCBI_NO_PROXY = "ncbi.nlm.nih.gov"
for _var in ("no_proxy", "NO_PROXY"):
    _cur = os.environ.get(_var, "")
    if _NCBI_NO_PROXY not in _cur:
        os.environ[_var] = (_cur + "," + _NCBI_NO_PROXY).strip(",")


def http_get_json(url, retries=3, backoff=2.0):
    headers = {"User-Agent": f"schizothoracinae-lit-radar/1.0 ({CONTACT_EMAIL})"}
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
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


def fetch_openalex(keyword, since_date, track):
    query = urllib.parse.quote(keyword)
    url = (
        "https://api.openalex.org/works"
        f"?filter=from_publication_date:{since_date},"
        f"type:article,"
        f"title_and_abstract.search:{query}"
        f"&sort=publication_date:desc&per_page=50&mailto={CONTACT_EMAIL}"
    )
    data = http_get_json(url)
    if not data:
        return []
    papers = []
    for work in data.get("results", []):
        title = work.get("title") or ""
        if not title:
            continue
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
        papers.append({
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
        })
    return papers


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


def fetch_pubmed(keyword, since_date, track):
    term = urllib.parse.quote(f'{keyword} AND ("{since_date}"[PDAT] : "3000"[PDAT])')
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pubmed&term={term}&retmode=json&retmax=50&sort=pub_date"
        f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
    )
    search_data = http_get_json(search_url)
    if not search_data:
        return []
    pmids = search_data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return []
    time.sleep(0.4)
    summary_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        f"?db=pubmed&id={','.join(pmids)}&retmode=json"
        f"&tool=schizothoracinae-lit-radar&email={CONTACT_EMAIL}"
    )
    summary_data = http_get_json(summary_url)
    if not summary_data:
        return []
    papers = []
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


def load_tiers_config(path=TIERS_PATH):
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    whitelist = set()
    for names in (cfg.get("whitelist") or {}).values():
        for n in names or []:
            whitelist.add(normalize_journal_name(n))
    thresholds = cfg.get("thresholds") or {}
    noise = [p.lower() for p in (cfg.get("noise_title_patterns") or [])]
    return {
        "whitelist": whitelist,
        "min_h_index": thresholds.get("min_h_index", 0),
        "min_2yr_mean_citedness": thresholds.get("min_2yr_mean_citedness", 0),
        "noise_title_patterns": noise,
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


def assign_tier(paper, metrics, cfg):
    title_l = (paper.get("title") or "").lower()
    jname = normalize_journal_name(paper.get("journal") or "")

    sid = paper.get("openalex_source_id")
    m = metrics.get(sid) if sid else None
    h_index = (m or {}).get("h_index")
    citedness = (m or {}).get("citedness")
    paper["journal_h_index"] = h_index
    paper["journal_citedness"] = citedness

    # bioRxiv preprints: valuable for methodology frontier (Track B), else general.
    if paper.get("source") == "bioRxiv":
        paper["tier"] = 2 if paper.get("track") == "B" else 3
        return

    if jname in cfg["whitelist"]:
        paper["tier"] = 1
    elif any(pat in title_l for pat in cfg["noise_title_patterns"]):
        paper["tier"] = 0
    elif (
        m
        and m.get("type") == "journal"
        and m.get("is_core")
        and ((h_index is not None and h_index >= cfg["min_h_index"])
             or (citedness is not None and citedness >= cfg["min_2yr_mean_citedness"]))
    ):
        paper["tier"] = 2
    elif jname:
        paper["tier"] = 3
    else:
        paper["tier"] = 0


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
            "A": {"label": "", "keywords": [], "papers": []},
            "B": {"label": "", "keywords": [], "papers": []},
        },
        "stats": {"total_count": 0, "new_this_week": 0, "weekly_trend": [], "tier_counts": {}},
    }


def main():
    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    config = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))
    tiers_cfg = load_tiers_config()
    existing = load_existing()
    total_added = 0

    for track_id, cfg_key in (("A", "track_a"), ("B", "track_b")):
        track_cfg = config[cfg_key]
        track_state = existing["tracks"].setdefault(
            track_id, {"label": "", "keywords": [], "papers": []}
        )
        track_state["label"] = track_cfg["label"]
        track_state["keywords"] = track_cfg["keywords"]

        new_papers = []
        for kw in track_cfg["keywords"]:
            new_papers.extend(fetch_openalex(kw, since_date, track_id))
            time.sleep(0.2)
            new_papers.extend(fetch_pubmed(kw, since_date, track_id))
            time.sleep(0.4)
        new_papers.extend(fetch_biorxiv_recent(track_cfg["keywords"], track_id))

        merged, added = merge_papers(track_state["papers"], new_papers)
        track_state["papers"] = merged
        total_added += added

    seen_ids = set()
    all_papers = []
    for p in existing["tracks"]["A"]["papers"] + existing["tracks"]["B"]["papers"]:
        key = p.get("id") or p.get("title", "").lower()
        if key not in seen_ids:
            seen_ids.add(key)
            all_papers.append(p)

    # Re-stamp tier for every paper each run so whitelist/threshold edits apply
    # retroactively to already-collected papers.
    metrics = enrich_source_metrics(all_papers)
    for p in all_papers:
        assign_tier(p, metrics, tiers_cfg)

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
