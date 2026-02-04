import json
import os
import pathlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"

MANIFEST_PATH = DATA / "manifest.json"
TOC_INDEX_PATH = DATA / "toc_index_pass10.json"
DEFAULT_ABBYY_MANIFEST = DATA / "abbyy_docx" / "abbyy_docx_manifest.json"
ABBYY_MANIFEST_PATH = pathlib.Path(
    os.environ.get("ABBYY_DOCX_MANIFEST", DEFAULT_ABBYY_MANIFEST)
)

OUTPUT_LOG = DATA / os.environ.get("ABBYY_SIM_OUTPUT", "abbyy_similarity_match.json")
OUTPUT_TEXT_DIR = os.environ.get("ABBYY_SIM_TEXT_OUTPUT")
OUTPUT_TEXT_DIR = DATA / OUTPUT_TEXT_DIR if OUTPUT_TEXT_DIR else None

SIM_THRESHOLD = float(os.environ.get("ABBYY_SIM_THRESHOLD", "0.75"))
SIM_WINDOW = int(os.environ.get("ABBYY_SIM_WINDOW", "40"))
MAX_NORM_LEN = int(os.environ.get("ABBYY_SIM_MAX_CHARS", "5000"))

SPEC_RE = re.compile(r"\bSA-\d{1,4}[A-Z]?\b")


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if MAX_NORM_LEN > 0:
        return text[:MAX_NORM_LEN]
    return text


def similarity(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def detect_spec(text):
    if not text:
        return None
    sample = text[:800].upper()
    match = SPEC_RE.search(sample)
    return match.group(0) if match else None


def load_toc_ranges():
    toc = load_json(TOC_INDEX_PATH, default={})
    ranges = {}
    for entry in toc.get("entries", []):
        spec = entry.get("spec")
        if not spec:
            continue
        start = entry.get("startGlobalPage")
        end = entry.get("rangeEndGlobalPage") or start
        if start and end and end >= start:
            ranges[spec.upper()] = (start, end)
    return ranges


def load_pdf_pages():
    manifest = load_json(MANIFEST_PATH, default={})
    pages = []
    for page in manifest.get("pages", []):
        page_json_rel = page.get("json")
        page_json = DATA / page_json_rel if page_json_rel else None
        page_data = load_json(page_json, default={}) if page_json else {}
        best_path = page_data.get("bestTextPath") or page.get("text") or page.get("textPath")
        if not best_path:
            continue
        text_path = DATA / best_path
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        pages.append(
            {
                "globalPageIndex": page.get("globalPageIndex") or page_data.get("globalPageIndex"),
                "textPath": best_path,
                "text": text,
                "norm": normalize_text(text),
                "spec": detect_spec(text),
            }
        )
    return pages


def load_abbyy_pages():
    manifest = load_json(ABBYY_MANIFEST_PATH, default={})
    pages = []
    for page in manifest.get("pages", []):
        text_path = DATA / page["textPath"]
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        pages.append(
            {
                "abbyyPageIndex": page.get("abbyyPageIndex"),
                "textPath": page["textPath"],
                "text": text,
                "norm": normalize_text(text),
                "spec": detect_spec(text),
            }
        )
    return pages


def candidate_indices(pages, ranges, spec, last_idx):
    if spec and spec in ranges:
        start, end = ranges[spec]
        return [idx for idx, p in enumerate(pages) if start <= p["globalPageIndex"] <= end]
    if last_idx is not None:
        start = max(0, last_idx - SIM_WINDOW)
        end = min(len(pages) - 1, last_idx + SIM_WINDOW)
        return list(range(start, end + 1))
    return list(range(len(pages)))


def main():
    if not ABBYY_MANIFEST_PATH.exists():
        raise FileNotFoundError(f"ABBYY manifest not found: {ABBYY_MANIFEST_PATH}")

    pdf_pages = load_pdf_pages()
    abbyy_pages = load_abbyy_pages()
    ranges = load_toc_ranges()

    if OUTPUT_TEXT_DIR:
        OUTPUT_TEXT_DIR.mkdir(parents=True, exist_ok=True)

    output_entries = []
    last_match_idx = None
    accepted = 0

    for page in abbyy_pages:
        candidates = candidate_indices(pdf_pages, ranges, page["spec"], last_match_idx)
        best_idx = None
        best_sim = 0.0
        for idx in candidates:
            sim = similarity(page["norm"], pdf_pages[idx]["norm"])
            if sim > best_sim:
                best_sim = sim
                best_idx = idx
        match = None
        if best_idx is not None:
            match = pdf_pages[best_idx]
            if best_sim >= SIM_THRESHOLD:
                last_match_idx = best_idx
                accepted += 1
                if OUTPUT_TEXT_DIR:
                    out_path = OUTPUT_TEXT_DIR / f"page-{match['globalPageIndex']:04d}.txt"
                    out_path.write_text(page["text"], encoding="utf-8")
        output_entries.append(
            {
                "abbyyPageIndex": page["abbyyPageIndex"],
                "abbyyTextPath": page["textPath"],
                "abbyySpec": page["spec"],
                "matchedGlobalPageIndex": match["globalPageIndex"] if match else None,
                "matchedTextPath": match["textPath"] if match else None,
                "matchedSpec": match["spec"] if match else None,
                "similarity": round(best_sim, 4),
                "accepted": best_sim >= SIM_THRESHOLD,
            }
        )

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "abbyyPages": len(abbyy_pages),
            "pdfPages": len(pdf_pages),
            "accepted": accepted,
            "similarityThreshold": SIM_THRESHOLD,
            "window": SIM_WINDOW,
            "outputTextDir": str(OUTPUT_TEXT_DIR) if OUTPUT_TEXT_DIR else None,
        },
        "pages": output_entries,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("ABBYY similarity match complete.")


if __name__ == "__main__":
    main()
