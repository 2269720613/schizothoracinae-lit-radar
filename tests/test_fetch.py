from datetime import datetime, timezone
from unittest.mock import patch

from scripts.fetch import (
    reconstruct_openalex_abstract,
    merge_papers,
    compute_stats,
    fetch_openalex,
    fetch_biorxiv_recent,
    normalize_pubmed_date,
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
            "primary_location": {"source": {"display_name": "Journal X"}},
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
