import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)


def detect_spec(text: str) -> str | None:
    if not text:
        return None
    lines = text.replace("\r\n", "\n").split("\n")[:10]
    for line in lines:
        line_norm = re.sub(r"\s+", " ", line.strip())
        if not line_norm:
            continue
        if "TABLE" in line_norm.upper():
            continue
        match = SPEC_RE.search(line_norm)
        if not match:
            continue
        spec = match.group("spec").upper()
        if line_norm.startswith(spec) or "SPECIFICATION" in line_norm.upper() or "ASME" in line_norm.upper():
            return spec
    header_block = " ".join(lines)
    match = SPEC_RE.search(header_block)
    return match.group("spec").upper() if match else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build spec ranges from header detection only."
    )
    parser.add_argument("--best-text", required=True, help="Folder with best_text pages.")
    parser.add_argument("--out", required=True, help="Output spec range JSON path.")
    args = parser.parse_args()

    best_text_dir = Path(args.best_text).resolve()
    pages = sorted(best_text_dir.glob("page-*.txt"))
    ranges = []
    current_spec = None
    current_start = None

    for page_path in pages:
        page_number = int(page_path.stem.replace("page-", ""))
        text = page_path.read_text(encoding="utf-8", errors="ignore")
        detected = detect_spec(text)
        if detected and detected != current_spec:
            if current_spec is not None and current_start is not None:
                ranges.append(
                    {
                        "spec": current_spec,
                        "startGlobalPage": current_start,
                        "endGlobalPage": page_number - 1,
                        "status": "derived",
                    }
                )
            current_spec = detected
            current_start = page_number

    if current_spec is not None and current_start is not None:
        last_page = int(pages[-1].stem.replace("page-", "")) if pages else current_start
        ranges.append(
            {
                "spec": current_spec,
                "startGlobalPage": current_start,
                "endGlobalPage": last_page,
                "status": "derived",
            }
        )

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "specsDetected": len({r["spec"] for r in ranges}),
            "ranges": len(ranges),
        },
        "ranges": ranges,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
