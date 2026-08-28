from datetime import datetime, timezone
from unittest.mock import patch

from scripts.fetch import (
    reconstruct_openalex_abstract,
    merge_papers,
    compute_stats,
    fetch_openalex,
    fetch_biorxiv_recent,
    normalize_pubmed_date,
    normalize_journal_name,
    assign_tier,
    enrich_source_metrics,
)


def test_reconstruct_openalex_abstract_orders_words_by_position():
    inverted = {"Despite": [0], "growing": [1], "interest": [2]}
    assert reconstruct_openalex_abstract(inverted) == "Despite growing interest"


def test_reconstruct_openalex_abstract_handles_empty():
    assert reconstruct_openalex_abstract({}) == ""
    assert reconstruct_openalex_abstract(None) == ""


def test_merge_papers_dedups_by_id():
    existing = [{"id": "10.1/a", "title": "A", "date": "2026-01-01"}]
    new = [
        {"id": "10.1/a", "title": "A (dup)", "date": "2026-01-01"},
        {"id": "10.1/b", "title": "B", "date": "2026-01-02"},
    ]
    merged, added = merge_papers(existing, new)
    assert added == 1
    assert len(merged) == 2
    assert {p["id"] for p in merged} == {"10.1/a", "10.1/b"}


def test_merge_papers_sorts_by_date_desc():
    existing = [{"id": "1", "title": "old", "date": "2026-01-01"}]
    new = [{"id": "2", "title": "new", "date": "2026-06-01"}]
    merged, _ = merge_papers(existing, new)
    assert [p["id"] for p in merged] == ["2", "1"]


def test_merge_papers_preserves_existing_records_without_id():
    existing = [{"id": "", "title": "No-DOI Preprint", "date": "2026-07-01"}]
    merged, added = merge_papers(existing, [])
    assert len(merged) == 1
    assert added == 0


def test_compute_stats_counts_new_this_week_and_trend_length():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    papers = [
        {"date": "2026-08-01"},
        {"date": "2026-07-01"},
    ]
    stats = compute_stats(papers, now)
    assert stats["total_count"] == 2
    assert stats["new_this_week"] == 1
    assert len(stats["weekly_trend"]) == 6


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_parses_results(mock_get):
    mock_get.return_value = {
        "results": [{
            "doi": "https://doi.org/10.1/xyz",
            "title": "Test paper",
            "authorships": [{"author": {"display_name": "Jane Doe"}}],
            "primary_location": {"source": {
                "id": "https://openalex.org/S123",
                "display_name": "Journal X",
                "type": "journal",
                "is_core": True,
            }},
            "publication_date": "2026-08-01",
            "id": "https://openalex.org/W1",
            "abstract_inverted_index": {"Hello": [0], "world": [1]},
        }]
    }
    papers = fetch_openalex("test", "2026-07-01", "A")
    assert len(papers) == 1
    p = papers[0]
    assert p["doi"] == "10.1/xyz"
    assert p["title"] == "Test paper"
    assert p["authors"] == ["Jane Doe"]
    assert p["journal"] == "Journal X"
    assert p["abstract"] == "Hello world"
    assert p["track"] == "A"
    assert p["source"] == "OpenAlex"
    assert p["openalex_source_id"] == "S123"
    assert p["source_type"] == "journal"
    assert p["source_is_core"] is True


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_skips_results_without_title(mock_get):
    mock_get.return_value = {"results": [{"title": "", "doi": "10.1/x"}]}
    assert fetch_openalex("test", "2026-07-01", "A") == []


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_normalizes_doi_case(mock_get):
    mock_get.return_value = {"results": [{
        "doi": "https://doi.org/10.1234/ABC",
        "title": "T", "authorships": [], "primary_location": {},
        "publication_date": "2026-08-01", "id": "https://openalex.org/W1",
    }]}
    papers = fetch_openalex("x", "2026-07-01", "A")
    assert papers[0]["doi"] == "10.1234/abc"


@patch("scripts.fetch.http_get_json")
def test_fetch_openalex_handles_null_source(mock_get):
    mock_get.return_value = {"results": [{
        "doi": "10.1/y", "title": "T", "authorships": [],
        "primary_location": {"source": None},
        "publication_date": "2026-08-01", "id": "https://openalex.org/W2",
    }]}
    papers = fetch_openalex("x", "2026-07-01", "A")
    assert papers[0]["journal"] == ""


def test_normalize_pubmed_date_handles_common_ncbi_formats():
    assert normalize_pubmed_date("2021 Dec 23") == "2021-12-23"
    assert normalize_pubmed_date("2021 Dec") == "2021-12-01"
    assert normalize_pubmed_date("2021") == "2021-01-01"
    assert normalize_pubmed_date("2026-08-01") == "2026-08-01"
    assert normalize_pubmed_date("") == ""


@patch("scripts.fetch.http_get_json")
def test_fetch_biorxiv_recent_filters_by_keyword(mock_get):
    mock_get.return_value = {
        "collection": [
            {"title": "Schizothorax genome", "abstract": "...", "doi": "10.1101/a",
             "date": "2026-08-01", "authors": "Li, X.; Wang, Y."},
            {"title": "Unrelated fruit fly study", "abstract": "...", "doi": "10.1101/b",
             "date": "2026-08-01", "authors": "Smith, A."},
        ]
    }
    papers = fetch_biorxiv_recent(["Schizothorax"], "A")
    assert len(papers) == 1
    assert papers[0]["title"] == "Schizothorax genome"
    assert papers[0]["authors"] == ["Li, X.", "Wang, Y."]


def _tier_cfg():
    return {
        "whitelist": {"molecular ecology", "bioinformatics"},
        "min_h_index": 120,
        "min_2yr_mean_citedness": 4.0,
        "noise_title_patterns": ["occurrence download"],
    }


def test_normalize_journal_name_lowercases_and_collapses_spaces():
    assert normalize_journal_name("  Molecular   Ecology ") == "molecular ecology"
    assert normalize_journal_name("Trends in Ecology & Evolution") == "trends in ecology & evolution"
    assert normalize_journal_name(None) == ""


def test_assign_tier_whitelist_is_tier1():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "Molecular Ecology", "source": "OpenAlex",
             "openalex_source_id": "S1"}
    assign_tier(paper, {"S1": {"type": "journal", "is_core": True, "h_index": 10, "citedness": 1}}, cfg)
    assert paper["tier"] == 1


def test_assign_tier_metrics_are_tier2():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "Some Core Journal", "source": "OpenAlex",
             "openalex_source_id": "S2"}
    assign_tier(paper, {"S2": {"type": "journal", "is_core": True, "h_index": 200, "citedness": 5}}, cfg)
    assert paper["tier"] == 2
    assert paper["journal_h_index"] == 200


def test_assign_tier_has_journal_below_threshold_is_tier3():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "Obscure Journal", "source": "OpenAlex",
             "openalex_source_id": "S3"}
    assign_tier(paper, {"S3": {"type": "journal", "is_core": True, "h_index": 5, "citedness": 0.5}}, cfg)
    assert paper["tier"] == 3


def test_assign_tier_whitelist_wins_over_noise_pattern():
    cfg = _tier_cfg()
    paper = {"title": "GBIF Occurrence Download for X", "journal": "Molecular Ecology",
             "source": "OpenAlex", "openalex_source_id": "S4"}
    # whitelist wins over noise by design (explicit curated venue)
    assign_tier(paper, {}, cfg)
    assert paper["tier"] == 1


def test_assign_tier_noise_pattern_without_whitelist_is_tier0():
    cfg = _tier_cfg()
    paper = {"title": "An Occurrence Download dataset", "journal": "Data in Brief",
             "source": "OpenAlex", "openalex_source_id": ""}
    assign_tier(paper, {}, cfg)
    assert paper["tier"] == 0


def test_assign_tier_no_journal_is_tier0():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "", "source": "OpenAlex", "openalex_source_id": ""}
    assign_tier(paper, {}, cfg)
    assert paper["tier"] == 0


def test_assign_tier_biorxiv_track_b_is_tier2():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "bioRxiv (preprint)", "source": "bioRxiv", "track": "B"}
    assign_tier(paper, {}, cfg)
    assert paper["tier"] == 2


@patch("scripts.fetch.http_get_json")
def test_enrich_source_metrics_batches_by_50(mock_get):
    def fake(url, *a, **k):
        # echo back one source per requested S-id
        sids = url.split("ids.openalex:")[1].split("&")[0].split("|")
        return {"results": [
            {"id": f"https://openalex.org/{s}", "summary_stats": {"h_index": 150, "2yr_mean_citedness": 6},
             "is_core": True, "type": "journal"} for s in sids
        ]}
    mock_get.side_effect = fake
    papers = [{"openalex_source_id": f"S{i}"} for i in range(60)]
    metrics = enrich_source_metrics(papers)
    assert len(metrics) == 60
    assert metrics["S59"]["h_index"] == 150
    # 60 unique ids => 2 batches => 2 http calls
    assert mock_get.call_count == 2
