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
    dedupe_papers,
    tier_papers,
    resolve_missing_source_ids,
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
        "whitelist_top": {"molecular biology and evolution", "bioinformatics"},
        "whitelist_fish": {"molecular ecology", "aquaculture"},
        "fish_title_patterns": ["fish", "schizothor"],
        "min_h_index": 120,
        "min_2yr_mean_citedness": 4.0,
        "noise_title_patterns": ["occurrence download"],
        "exclude_title_patterns": [],
        "min_tier": 3,
    }


def test_normalize_journal_name_lowercases_and_collapses_spaces():
    assert normalize_journal_name("  Molecular   Ecology ") == "molecular ecology"
    assert normalize_journal_name("Trends in Ecology & Evolution") == "trends in ecology & evolution"
    assert normalize_journal_name(None) == ""


def test_assign_tier_top_whitelist_non_fish_is_tier1():
    cfg = _tier_cfg()
    paper = {"title": "Centromere Evolution Across Eukaryotes", "journal": "Bioinformatics",
             "source": "OpenAlex", "openalex_source_id": "S1"}
    assign_tier(paper, {}, cfg)
    assert paper["tier"] == 1
    assert paper["is_fish"] is False


def test_assign_tier_fish_whitelist_requires_fish_paper():
    cfg = _tier_cfg()
    fish_paper = {"title": "Population Genomics of Tibetan Fish", "journal": "Molecular Ecology",
                  "source": "OpenAlex", "openalex_source_id": "S1"}
    assign_tier(fish_paper, {}, cfg)
    assert fish_paper["tier"] == 1
    assert fish_paper["is_fish"] is True
    non_fish = {"title": "Centromere Assembly in Maize", "journal": "Molecular Ecology",
                "source": "OpenAlex", "openalex_source_id": "S2"}
    assign_tier(non_fish, {}, cfg)
    assert non_fish["tier"] == 3


def test_assign_tier_track_a_is_fish_by_definition():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "Molecular Ecology", "track": "A", "source": "OpenAlex"}
    assign_tier(paper, {}, cfg)
    assert paper["is_fish"] is True
    assert paper["tier"] == 1


def test_assign_tier_fish_title_pattern_is_word_start_anchored():
    cfg = _tier_cfg()
    fishery = {"title": "A New Framework for Fishery Stock Assessment", "journal": "Aquaculture",
               "source": "OpenAlex"}
    assign_tier(fishery, {}, cfg)
    assert fishery["is_fish"] is True
    assert fishery["tier"] == 1
    catfish = {"title": "Catfish Genome Assembly", "journal": "Aquaculture", "source": "OpenAlex"}
    assign_tier(catfish, {}, cfg)
    assert catfish["is_fish"] is False


def test_assign_tier_metrics_path_requires_fish():
    cfg = _tier_cfg()
    metrics = {"S2": {"type": "journal", "is_core": True, "h_index": 200, "citedness": 5}}
    fish_paper = {"title": "Schizothorax Population Structure", "journal": "Some Core Journal",
                  "source": "OpenAlex", "openalex_source_id": "S2"}
    assign_tier(fish_paper, metrics, cfg)
    assert fish_paper["tier"] == 2
    assert fish_paper["journal_h_index"] == 200
    non_fish = {"title": "Centromere Drive in Plants", "journal": "Some Core Journal",
                "source": "OpenAlex", "openalex_source_id": "S2"}
    assign_tier(non_fish, metrics, cfg)
    assert non_fish["tier"] == 3


def test_assign_tier_has_journal_below_threshold_is_tier3():
    cfg = _tier_cfg()
    paper = {"title": "T", "journal": "Obscure Journal", "source": "OpenAlex",
             "openalex_source_id": "S3"}
    assign_tier(paper, {"S3": {"type": "journal", "is_core": True, "h_index": 5, "citedness": 0.5}}, cfg)
    assert paper["tier"] == 3


def test_assign_tier_whitelist_wins_over_noise_pattern():
    cfg = _tier_cfg()
    paper = {"title": "GBIF Occurrence Download for Tibetan Fish", "journal": "Molecular Ecology",
             "source": "OpenAlex", "openalex_source_id": "S4"}
    # fish whitelist wins over noise by design (explicit curated venue)
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


def test_assign_tier_biorxiv_fish_tier2_non_fish_tier3():
    cfg = _tier_cfg()
    fish_preprint = {"title": "Schizothorax Reference Genome", "journal": "bioRxiv (preprint)",
                     "source": "bioRxiv", "track": "B"}
    assign_tier(fish_preprint, {}, cfg)
    assert fish_preprint["tier"] == 2
    non_fish = {"title": "Centromere Assembly Pipeline", "journal": "bioRxiv (preprint)",
                "source": "bioRxiv", "track": "B"}
    assign_tier(non_fish, {}, cfg)
    assert non_fish["tier"] == 3


def test_assign_tier_exclude_pattern_beats_whitelist_and_biorxiv():
    cfg = _tier_cfg()
    cfg["exclude_title_patterns"] = ["stress"]
    venue_paper = {"title": "Acute Heat Stress Response in Carp", "journal": "Molecular Ecology",
                   "source": "OpenAlex", "openalex_source_id": "S1"}
    assign_tier(venue_paper, {}, cfg)
    assert venue_paper["tier"] == 0
    preprint = {"title": "Thermal Stress Tolerance Experiment", "journal": "bioRxiv (preprint)",
                "source": "bioRxiv", "track": "B"}
    assign_tier(preprint, {}, cfg)
    assert preprint["tier"] == 0


def test_assign_tier_min_tier_downgrades_below_threshold_to_tier0():
    cfg = _tier_cfg()
    cfg["min_tier"] = 2
    paper = {"title": "T", "journal": "Obscure Journal", "source": "OpenAlex",
             "openalex_source_id": "S3"}
    assign_tier(paper, {"S3": {"type": "journal", "is_core": True, "h_index": 5, "citedness": 0.5}}, cfg)
    assert paper["tier"] == 0


def test_assign_tier_min_tier_keeps_whitelist_and_tier2():
    cfg = _tier_cfg()
    cfg["min_tier"] = 2
    top_paper = {"title": "T", "journal": "Bioinformatics", "source": "OpenAlex"}
    assign_tier(top_paper, {}, cfg)
    assert top_paper["tier"] == 1
    fish_whitelist_paper = {"title": "T", "journal": "Molecular Ecology", "source": "OpenAlex",
                            "track": "A"}
    assign_tier(fish_whitelist_paper, {}, cfg)
    assert fish_whitelist_paper["tier"] == 1
    fish_metrics_paper = {"title": "T", "journal": "Some Core Journal", "source": "OpenAlex",
                          "openalex_source_id": "S2", "track": "A"}
    assign_tier(fish_metrics_paper, {"S2": {"type": "journal", "is_core": True, "h_index": 200, "citedness": 5}}, cfg)
    assert fish_metrics_paper["tier"] == 2


@patch("scripts.fetch.http_get_json")
def test_resolve_missing_source_ids_matches_exact_and_prefix(mock_get):
    def fake(url, *a, **k):
        if "Molecular%20Ecology" in url or "Molecular+Ecology" in url or "Molecular Ecology" in url:
            return {"results": [
                {"id": "https://openalex.org/S1", "display_name": "Molecular Ecology", "type": "journal"},
            ]}
        if "Aquaculture" in url:
            return {"results": [
                {"id": "https://openalex.org/S2",
                 "display_name": "Aquaculture (Amsterdam, Netherlands)", "type": "journal"},
            ]}
        if "Weird" in url:
            return {"results": [
                {"id": "https://openalex.org/S9", "display_name": "Weird Repository", "type": "repository"},
            ]}
        return {"results": []}

    mock_get.side_effect = fake
    papers = [
        {"journal": "Molecular Ecology"},
        {"journal": "Aquaculture (Amsterdam, Netherlands)"},
        {"journal": "Weird Journal"},            # repository hit only -> unresolved
        {"journal": "bioRxiv (preprint)"},       # skipped
        {"journal": ""},                          # skipped
        {"openalex_source_id": "S8", "journal": "Already Resolved"},  # skipped
    ]
    resolved = resolve_missing_source_ids(papers)
    assert resolved == 2
    assert papers[0]["openalex_source_id"] == "S1"
    assert papers[1]["openalex_source_id"] == "S2"
    assert "openalex_source_id" not in papers[2]
    assert "openalex_source_id" not in papers[3]
    assert "openalex_source_id" not in papers[4]
    assert papers[5]["openalex_source_id"] == "S8"


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


def test_dedupe_papers_keeps_first_occurrence_per_id():
    copy_a = {"id": "10.1/x", "title": "X", "track": "A"}
    copy_b = {"id": "10.1/x", "title": "X", "track": "B"}
    assert dedupe_papers([copy_a, copy_b]) == [copy_a]


@patch("scripts.fetch.enrich_source_metrics", return_value={})
def test_tier_papers_stamps_every_duplicate_copy(mock_enrich):
    cfg = _tier_cfg()
    copy_a = {"id": "10.1/y", "title": "Y", "journal": "Bioinformatics",
              "source": "OpenAlex", "openalex_source_id": ""}
    copy_b = dict(copy_a, track="B")
    tier_papers([copy_a, copy_b], cfg)
    assert copy_a["tier"] == 1
    assert copy_b["tier"] == 1
