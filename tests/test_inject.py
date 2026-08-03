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


def test_render_against_real_template_currently_has_duplicate_placeholder():
    real_template = (Path(__file__).resolve().parent.parent / "template" / "dashboard.html").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        render(real_template, {"a": 1})
