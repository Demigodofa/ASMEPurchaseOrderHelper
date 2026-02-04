import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a minimal manifest for stage 4 exports.")
    parser.add_argument("--pdf", required=True, help="Source PDF path.")
    parser.add_argument("--out", required=True, help="Output manifest.json path.")
    parser.add_argument(
        "--source-name",
        required=False,
        help="Optional sourcePdf name override (defaults to PDF filename).",
    )
    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()
    out_path = Path(args.out).resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    source_name = args.source_name or pdf_path.name
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)

    pages = []
    for idx in range(1, page_count + 1):
        pages.append(
            {
                "globalPageIndex": idx,
                "sourcePdf": source_name,
                "sourcePageNumber": idx,
            }
        )

    manifest = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "sourcePdfs": [source_name],
        "pages": pages,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
