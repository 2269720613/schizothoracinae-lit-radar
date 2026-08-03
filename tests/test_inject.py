import json
from pathlib import Path

import pytest

from scripts.inject import render, PLACEHOLDER


def test_render_replaces_placeholder():
    template = f'<div>{PLACEHOLDER}</div>'
    result = render(template, {"a": 1})
    assert PLACEHOLDER not in result
    assert '{"a": 1}' in result


def test_render_escapes_script_close_tag_in_data():
    template = f'<script id="lit-radar-data" type="application/json">{PLACEHOLDER}</script>'
    data = {"title": "</script><script>alert(1)</script>"}
    result = render(template, data)
    assert result.count("</script>") == 1


def test_render_missing_placeholder_raises():
    with pytest.raises(ValueError):
        render("<div>no placeholder here</div>", {"a": 1})


def test_render_raises_when_placeholder_appears_multiple_times():
    template = f'<div>{PLACEHOLDER}</div><script>if (x !== \'{PLACEHOLDER}\') {{}}</script>'
    with pytest.raises(ValueError):
        render(template, {"a": 1})


def test_render_against_real_template_succeeds():
    real_template = (Path(__file__).resolve().parent.parent / "template" / "dashboard.html").read_text(encoding="utf-8")
    data_obj = {
        "generated_at": "2026-08-04T00:00:00Z",
        "tracks": {
            "A": {"label": "x", "keywords": [], "papers": []},
            "B": {"label": "y", "keywords": [], "papers": []},
        },
        "stats": {"total_count": 0, "new_this_week": 0, "weekly_trend": []},
    }

    result = render(real_template, data_obj)

    assert PLACEHOLDER not in result


def test_render_against_real_template_with_apostrophe_in_title_does_not_break_js():
    real_template = (Path(__file__).resolve().parent.parent / "template" / "dashboard.html").read_text(encoding="utf-8")
    data_obj = {
        "generated_at": "2026-08-04T00:00:00Z",
        "tracks": {
            "A": {
                "label": "x",
                "keywords": [],
                "papers": [
                    {
                        "id": "1",
                        "title": "O'Brien's finding",
                        "authors": "O'Brien",
                        "journal": "J",
                        "date": "2026-01-01",
                        "doi": "10.1/x",
                        "url": "http://example.com",
                        "abstract": "abc",
                        "track": "A",
                        "source": "test",
                    }
                ],
            },
            "B": {"label": "y", "keywords": [], "papers": []},
        },
        "stats": {"total_count": 1, "new_this_week": 1, "weekly_trend": []},
    }

    result = render(real_template, data_obj)

    data_json_str = json.dumps(data_obj, ensure_ascii=False).replace("</script>", "<\\/script>")
    assert result.count(data_json_str) == 1
    assert "O'Brien" in result
