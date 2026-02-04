import json
import os
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

MATCH_LOG = DATA / os.environ.get("ABBYY_SIM_LOG", "abbyy_similarity_greyscale.json")
SOURCE_DIR = DATA / os.environ.get("ABBYY_SIM_TEXT_DIR", "abbyy_similarity_greyscale_best")
BEST_TEXT_DIR = DATA / "best_text" / "pages"
BACKUP_DIR = DATA / os.environ.get("ABBYY_SIM_BACKUP", "best_text_similarity_backup")
OUTPUT_LOG = DATA / os.environ.get("ABBYY_SIM_MERGE_LOG", "abbyy_similarity_merge.json")


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    if not MATCH_LOG.exists():
        raise FileNotFoundError(f"Match log not found: {MATCH_LOG}")
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"Source dir not found: {SOURCE_DIR}")
    BEST_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    data = load_json(MATCH_LOG, default={})
    pages = [p for p in data.get("pages", []) if p.get("accepted")]
    merged = []
    skipped = []

    for entry in pages:
        global_index = entry.get("matchedGlobalPageIndex")
        if not global_index:
            skipped.append({"entry": entry, "reason": "missing global index"})
            continue
        src_path = SOURCE_DIR / f"page-{global_index:04d}.txt"
        if not src_path.exists():
            skipped.append({"entry": entry, "reason": "missing source text"})
            continue
        dest_path = BEST_TEXT_DIR / f"page-{global_index:04d}.txt"
        if dest_path.exists():
            backup_path = BACKUP_DIR / f"page-{global_index:04d}.txt"
            backup_path.write_text(dest_path.read_text(encoding="utf-8"), encoding="utf-8")
        dest_path.write_text(src_path.read_text(encoding="utf-8"), encoding="utf-8")
        merged.append(global_index)

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "acceptedMatches": len(pages),
            "merged": len(merged),
            "skipped": len(skipped),
        },
        "mergedGlobalPages": sorted(merged),
        "skipped": skipped,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("ABBYY similarity merge into best_text complete.")


if __name__ == "__main__":
    main()
