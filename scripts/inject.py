#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.fetch import compute_stats, dedupe_papers  # noqa: E402

TEMPLATE_PATH = ROOT / "template" / "dashboard.html"
DATA_PATH = ROOT / "data" / "data.json"
OUTPUT_PATH = ROOT / "dist" / "dashboard.html"
PLACEHOLDER = "__LIT_RADAR_DATA__"


def render(template_str, data_obj):
    count = template_str.count(PLACEHOLDER)
    if count != 1:
        raise ValueError(
            f"expected exactly 1 occurrence of {PLACEHOLDER} in template, found {count}"
        )
    data_json_str = json.dumps(data_obj, ensure_ascii=False).replace("</script>", "<\\/script>")
    return template_str.replace(PLACEHOLDER, data_json_str)


def main():
    if not TEMPLATE_PATH.exists():
        print(f"ERROR: template not found at {TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    if not DATA_PATH.exists():
        print(f"ERROR: data not found at {DATA_PATH}", file=sys.stderr)
        sys.exit(1)

    template_str = TEMPLATE_PATH.read_text(encoding="utf-8")
    data_obj = json.loads(DATA_PATH.read_text(encoding="utf-8"))

    # The dashboard only ships visible papers: with the 5-year backfill the
    # tier-0 tail would bloat dashboard.html into tens of MB. Hidden papers
    # stay in data/data.json (source of truth) for future re-tiering.
    hidden = 0
    for track in (data_obj.get("tracks") or {}).values():
        papers = track.get("papers") or []
        kept = [p for p in papers if p.get("tier", 3) != 0]
        hidden += len(papers) - len(kept)
        track["papers"] = kept

    visible = dedupe_papers(
        [p for t in (data_obj.get("tracks") or {}).values() for p in t["papers"]]
    )
    data_obj["stats"] = compute_stats(visible, datetime.now(timezone.utc))

    output = render(template_str, data_obj)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(
        f"inject.py done: wrote {OUTPUT_PATH} ({len(output)} bytes, "
        f"{len(visible)} visible papers, {hidden} hidden omitted)"
    )


if __name__ == "__main__":
    main()
