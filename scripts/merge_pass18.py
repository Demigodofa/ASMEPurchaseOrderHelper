import json
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
MANIFEST_PATH = DATA / "manifest.json"
PAGE_DIR = DATA / "pages"
BEST_TEXT_DIR = DATA / "best_text" / "pages"
FULL_OCR_DIR = DATA / "full_ocr_highdpi"
OUTPUT_LOG = DATA / "merge_pass18.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    return alpha / max(1, len(text))


def main():
    manifest = load_json(MANIFEST_PATH)
    BEST_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    output = []
    updated = 0
    for page in manifest.get("pages", []):
        idx = page["globalPageIndex"]
        best_path = BEST_TEXT_DIR / f"page-{idx:04d}.txt"
        full_path = FULL_OCR_DIR / f"page-{idx:04d}.txt"

        if not full_path.exists():
            continue

        full_text = full_path.read_text(encoding="utf-8", errors="ignore")
        full_len = len(full_text)
        full_alpha = alpha_ratio(full_text)

        best_text = ""
        best_len = 0
        best_alpha = 0.0
        if best_path.exists():
            best_text = best_path.read_text(encoding="utf-8", errors="ignore")
            best_len = len(best_text)
            best_alpha = alpha_ratio(best_text)

        if full_alpha > best_alpha or (full_alpha == best_alpha and full_len > best_len):
            best_path.write_text(full_text, encoding="utf-8")
            updated += 1
            page_json_path = PAGE_DIR / f"page-{idx:04d}.json"
            if page_json_path.exists():
                page_json = load_json(page_json_path)
                page_json["bestTextPath"] = str(best_path.relative_to(DATA))
                page_json["bestTextSource"] = "full_ocr_highdpi"
                page_json["bestTextLength"] = full_len
                page_json["bestTextAlphaRatio"] = round(full_alpha, 3)
                page_json_path.write_text(json.dumps(page_json, indent=2), encoding="utf-8")

        output.append(
            {
                "globalPageIndex": idx,
                "updated": full_alpha > best_alpha or (full_alpha == best_alpha and full_len > best_len),
                "fullLength": full_len,
                "fullAlphaRatio": round(full_alpha, 3),
                "bestLengthBefore": best_len,
                "bestAlphaBefore": round(best_alpha, 3),
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "pagesEvaluated": len(output),
            "pagesUpdated": updated,
        },
        "pages": output,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Merge pass 18 complete.")


if __name__ == "__main__":
    main()
