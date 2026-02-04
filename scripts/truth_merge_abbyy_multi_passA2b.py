import json
import os
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

DEFAULT_OUTPUT_DIR = DATA / "truth_abbyy_multi"
OUTPUT_DIR = DATA / os.environ.get("ABBYY_TRUTH_MULTI_OUTPUT", "truth_abbyy_multi")
PAGES_DIR = OUTPUT_DIR / "pages"
OUTPUT_LOG = OUTPUT_DIR / "truth_merge_multi_passA2b.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def find_logs():
    override = os.environ.get("ABBYY_TRUTH_MULTI_LOGS")
    if override:
        return [pathlib.Path(p) for p in override.split(os.pathsep) if p]
    return sorted(DATA.glob("truth_abbyy*/truth_merge_passA2.json"))


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    logs = [path for path in find_logs() if path.exists()]
    if not logs:
        raise FileNotFoundError("No truth_merge_passA2.json logs found.")

    chosen = {}
    sources = []
    for log_path in logs:
        data = load_json(log_path)
        source_name = log_path.parent.name
        sources.append(source_name)
        for entry in data.get("pages", []):
            if entry.get("decision") != "accepted":
                continue
            text_rel = entry.get("abbyyTextPath")
            if not text_rel:
                continue
            text_path = DATA / text_rel
            if not text_path.exists():
                continue
            text = text_path.read_text(encoding="utf-8")
            key = entry.get("globalPageIndex")
            if key is None:
                continue
            score = (
                entry.get("pageSimilarity", 0.0),
                entry.get("alignSimilarity", 0.0),
                len(text),
            )
            current = chosen.get(key)
            if not current or score > current["score"]:
                chosen[key] = {
                    "score": score,
                    "text": text,
                    "source": source_name,
                    "abbyyTextPath": text_rel,
                    "alignSimilarity": entry.get("alignSimilarity", 0.0),
                    "pageSimilarity": entry.get("pageSimilarity", 0.0),
                    "anchors": entry.get("anchors", []),
                    "abbyyPageIndex": entry.get("abbyyPageIndex"),
                }

    output_entries = []
    for global_index in sorted(chosen.keys()):
        info = chosen[global_index]
        out_path = PAGES_DIR / f"page-{global_index:04d}.txt"
        out_path.write_text(info["text"], encoding="utf-8")
        output_entries.append(
            {
                "globalPageIndex": global_index,
                "source": info["source"],
                "abbyyPageIndex": info["abbyyPageIndex"],
                "abbyyTextPath": info["abbyyTextPath"],
                "outputTextPath": str(out_path.relative_to(DATA)),
                "pageSimilarity": round(info["pageSimilarity"], 4),
                "alignSimilarity": round(info["alignSimilarity"], 4),
                "anchors": info["anchors"],
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "sources": sources,
            "acceptedPages": len(output_entries),
            "logsFound": len(logs),
        },
        "pages": output_entries,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Truth merge multi pass A2b complete.")


if __name__ == "__main__":
    main()
