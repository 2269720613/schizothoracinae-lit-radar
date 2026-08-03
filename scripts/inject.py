#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
    output = render(template_str, data_obj)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"inject.py done: wrote {OUTPUT_PATH} ({len(output)} bytes)")


if __name__ == "__main__":
    main()
