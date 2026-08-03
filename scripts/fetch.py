#!/usr/bin/env python3
import json
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

LOOKBACK_DAYS = 7
CONTACT_EMAIL = "ccj13169@gmail.com"


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
        f"?search={query}"
        f"&filter=from_publication_date:{since_date}"
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
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        papers.append({
            "id": doi or work.get("id", ""),
            "title": title,
            "authors": [a["author"]["display_name"] for a in work.get("authorships", [])],
            "journal": (work.get("primary_location") or {}).get("source", {}).get("display_name", "") or "",
            "date": work.get("publication_date", ""),
            "doi": doi,
            "url": work.get("id", ""),
            "abstract": reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
            "track": track,
            "source": "OpenAlex",
        })
    return papers


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
                doi = aid.get("value", "")
        papers.append({
            "id": doi or uid,
            "title": item.get("title", ""),
            "authors": [a.get("name", "") for a in item.get("authors", [])],
            "journal": item.get("fulljournalname", ""),
            "date": item.get("pubdate", ""),
            "doi": doi,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            "abstract": "",
            "track": track,
            "source": "PubMed",
        })
    return papers


def fetch_biorxiv_recent(keywords, track):
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
        papers.append({
            "id": item.get("doi", ""),
            "title": item.get("title", ""),
            "authors": [a.strip() for a in item.get("authors", "").split(";") if a.strip()],
            "journal": "bioRxiv (preprint)",
            "date": item.get("date", ""),
            "doi": item.get("doi", ""),
            "url": f"https://doi.org/{item.get('doi','')}" if item.get("doi") else "",
            "abstract": item.get("abstract", ""),
            "track": track,
            "source": "bioRxiv",
        })
    return papers


def merge_papers(existing_papers, new_papers):
    by_id = {p["id"]: p for p in existing_papers if p.get("id")}
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
        trend.append({"week": week_start.strftime("%Y-W%V"), "count": count})
    return {"total_count": total, "new_this_week": new_this_week, "weekly_trend": trend}


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return {
        "generated_at": "",
        "tracks": {
            "A": {"label": "", "keywords": [], "papers": []},
            "B": {"label": "", "keywords": [], "papers": []},
        },
        "stats": {"total_count": 0, "new_this_week": 0, "weekly_trend": []},
    }


def main():
    now = datetime.now(timezone.utc)
    since_date = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    config = yaml.safe_load(KEYWORDS_PATH.read_text(encoding="utf-8"))
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

    all_papers = existing["tracks"]["A"]["papers"] + existing["tracks"]["B"]["papers"]
    existing["stats"] = compute_stats(all_papers, now)
    existing["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fetch.py done: +{total_added} new papers, total={len(all_papers)}")


if __name__ == "__main__":
    main()
