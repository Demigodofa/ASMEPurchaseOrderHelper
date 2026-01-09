import json
import os
import re
from datetime import datetime, timezone


def alpha_ratio(text):
    if not text:
        return 0.0
    alpha = len(re.findall(r"[A-Za-z]", text))
    return alpha / max(1, len(text))


def is_low_confidence(text):
    return len(text) < 300 or alpha_ratio(text) < 0.2


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    manifest_path = os.path.join(output_root, "manifest.json")
    best_root = os.path.join(output_root, "best_text")
    best_pages = os.path.join(best_root, "pages")

    os.makedirs(best_pages, exist_ok=True)

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    combined_path = os.path.join(best_root, "combined.txt")
    combined_lines = []

    stats = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "pagesTotal": 0,
        "ocrPreferred": 0,
        "pass1Preferred": 0,
    }

    for page_entry in manifest.get("pages", []):
        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        base_text = page_json.get("text", "") or ""
        best_text = base_text
        best_source = "pass1"

        ocr_path = page_json.get("ocrTextPath")
        if page_json.get("ocrApplied") and ocr_path:
            abs_ocr = os.path.join(output_root, ocr_path)
            if os.path.exists(abs_ocr):
                with open(abs_ocr, "r", encoding="utf-8") as handle:
                    ocr_text = handle.read()

                base_low = is_low_confidence(base_text)
                if base_low or len(ocr_text) >= len(base_text) or alpha_ratio(ocr_text) > alpha_ratio(base_text):
                    if ocr_text.strip():
                        best_text = ocr_text
                        best_source = "ocr"

        base_name = f"page-{page_json.get('globalPageIndex', 0):04d}"
        best_path_rel = f"best_text/pages/{base_name}.txt"
        best_path = os.path.join(output_root, best_path_rel)

        with open(best_path, "w", encoding="utf-8") as handle:
            handle.write(best_text)

        page_json["bestTextPath"] = best_path_rel
        page_json["bestTextSource"] = best_source
        page_json["bestTextLength"] = len(best_text)
        page_json["bestTextAlphaRatio"] = round(alpha_ratio(best_text), 4)

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        combined_lines.append(f"==== page {page_json.get('globalPageIndex')} ====")
        combined_lines.append(best_text)

        stats["pagesTotal"] += 1
        if best_source == "ocr":
            stats["ocrPreferred"] += 1
        else:
            stats["pass1Preferred"] += 1

    with open(combined_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(combined_lines))

    stats_path = os.path.join(output_root, "merge_pass6.json")
    with open(stats_path, "w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2)

    print("Merge pass complete.")


if __name__ == "__main__":
    main()
