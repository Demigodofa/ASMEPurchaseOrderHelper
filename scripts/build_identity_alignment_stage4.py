import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an identity alignment map for stage 4."
    )
    parser.add_argument("--pages", type=int, required=True, help="Number of pages.")
    parser.add_argument("--out", required=True, help="Output alignment JSON path.")
    args = parser.parse_args()

    matches = []
    for idx in range(1, args.pages + 1):
        matches.append(
            {
                "otherPageNumber": idx,
                "basePageNumber": idx,
                "detectedPageNumber": idx,
                "method": "identity",
                "score": 1.0,
            }
        )

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "basePages": args.pages,
            "otherPages": args.pages,
            "averageScore": 1.0,
        },
        "matches": matches,
    }

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
