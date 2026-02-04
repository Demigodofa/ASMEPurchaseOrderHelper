import json
import os
import pathlib
import re
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
SPEC_CORPUS_DIR = DATA / "spec_corpus"
SPEC_INDEX_PATH = SPEC_CORPUS_DIR / "spec_corpus_index.json"
OUTPUT_LOG = DATA / "fill_placeholders_from_abbyy.json"

SPEC_RE = re.compile(r"\bSA-\d{1,4}[A-Z]?\b")


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value):
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower() or "abbyy"


def get_source_dirs():
    override = os.environ.get("ABBYY_SOURCE_DIRS")
    if override:
        return [DATA / p for p in override.split(os.pathsep) if p]
    candidates = []
    for name in ("abbyy_docx", "abbyy_docx_greyscale"):
        path = DATA / name
        if path.exists():
            candidates.append(path)
    return candidates


def load_abbyy_pages(source_dir):
    manifest = source_dir / "abbyy_docx_manifest.json"
    data = load_json(manifest, default=None)
    if not data:
        return []
    pages = []
    for page in data.get("pages", []):
        text_path = DATA / page["textPath"]
        text = text_path.read_text(encoding="utf-8") if text_path.exists() else ""
        pages.append(
            {
                "abbyyPageIndex": page["abbyyPageIndex"],
                "textPath": page["textPath"],
                "text": text,
            }
        )
    return pages


def page_header_spec(text):
    if not text:
        return None
    sample = text[:800].upper()
    matches = SPEC_RE.findall(sample)
    if matches:
        return matches[0].upper()
    return None


def header_positions(pages):
    headers = []
    for idx, page in enumerate(pages):
        spec = page_header_spec(page["text"])
        if spec:
            headers.append((idx, spec))
    return headers


def extract_spec_block(pages, headers, target_spec):
    for idx, spec in headers:
        if spec != target_spec:
            continue
        start = idx
        next_indices = [i for i, _ in headers if i > idx]
        end = min(next_indices) if next_indices else len(pages)
        return pages[start:end]
    return []


def confidence_for_block(pages):
    if not pages:
        return 0.0
    first = pages[0]["text"]
    if "SPECIFICATION FOR" in first.upper():
        return 0.9
    return 0.7


def main():
    spec_index = load_json(SPEC_INDEX_PATH, default=[])
    spec_entries = {entry["spec"].upper(): entry for entry in spec_index if entry.get("spec")}

    placeholders = [
        entry["spec"].upper()
        for entry in spec_index
        if entry.get("spec") and entry.get("placeholder")
    ]

    sources = []
    filled = []
    for source_dir in get_source_dirs():
        pages = load_abbyy_pages(source_dir)
        if not pages:
            continue
        source_name = source_dir.name
        sources.append(source_name)
        headers = header_positions(pages)
        for spec in placeholders:
            if spec in filled:
                continue
            block = extract_spec_block(pages, headers, spec)
            if not block:
                continue
            spec_dir = SPEC_CORPUS_DIR / spec
            spec_dir.mkdir(parents=True, exist_ok=True)
            combined = "\n\n".join(page["text"].strip() for page in block if page["text"].strip())
            spec_txt_path = spec_dir / "spec.txt"
            spec_txt_path.write_text(combined + "\n", encoding="utf-8")
            spec_json = {
                "createdUtc": datetime.now(timezone.utc).isoformat(),
                "spec": spec,
                "rangeStart": None,
                "rangeEnd": None,
                "pages": [
                    {
                        "abbyyPageIndex": page["abbyyPageIndex"],
                        "textPath": page["textPath"],
                        "source": source_name,
                    }
                    for page in block
                ],
                "placeholder": False,
                "sourceTruth": {
                    "source": source_name,
                    "method": "abbyy-docx-header",
                    "confidence": confidence_for_block(block),
                },
            }
            (spec_dir / "spec.json").write_text(
                json.dumps(spec_json, indent=2), encoding="utf-8"
            )
            entry = spec_entries.get(spec)
            if entry:
                entry["pageCount"] = len(block)
                entry["placeholder"] = False
            else:
                spec_index.append(
                    {
                        "spec": spec,
                        "rangeStart": None,
                        "rangeEnd": None,
                        "pageCount": len(block),
                        "path": f"spec_corpus\\{spec}\\spec.json",
                        "placeholder": False,
                    }
                )
            filled.append(spec)

    if filled:
        SPEC_INDEX_PATH.write_text(json.dumps(spec_index, indent=2), encoding="utf-8")

    result = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "placeholders": len(placeholders),
            "filled": len(filled),
            "sources": sources,
        },
        "filledSpecs": filled,
    }
    OUTPUT_LOG.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Fill placeholders from ABBYY complete.")


if __name__ == "__main__":
    main()
