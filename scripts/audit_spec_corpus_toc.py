import json
import os
import pathlib
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
TOC_INDEX_PATH = DATA / "toc_index_pass10.json"
TOC_ABBYY_PATH = DATA / "toc_abbyy_docx_pass8d.json"
SPEC_CORPUS_DIR = DATA / "spec_corpus"
SPEC_INDEX_PATH = SPEC_CORPUS_DIR / "spec_corpus_index.json"
OUTPUT_LOG = DATA / "spec_corpus_toc_audit.json"


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def spec_key(spec):
    return spec.upper().strip()


def build_toc_map(toc_index):
    toc_map = {}
    for entry in toc_index.get("entries", []):
        spec = entry.get("spec")
        if not spec:
            continue
        key = spec_key(spec)
        start = entry.get("startGlobalPage")
        end = entry.get("rangeEndGlobalPage") or start
        toc_map[key] = {
            "spec": key,
            "start": start,
            "end": end,
            "tocLine": entry.get("tocLine"),
        }
    return toc_map


def merge_abbyy_toc(toc_map, abbyy_toc):
    for entry in abbyy_toc.get("entries", []):
        spec = entry.get("spec")
        if not spec:
            continue
        key = spec_key(spec)
        if key in toc_map:
            continue
        toc_map[key] = {
            "spec": key,
            "start": None,
            "end": None,
            "tocLine": entry.get("tocLine"),
        }


def load_abbyy_toc_paths():
    override = os.environ.get("ABBYY_TOC_PATHS")
    if override:
        return [pathlib.Path(p) for p in override.split(os.pathsep) if p]
    return [TOC_ABBYY_PATH] if TOC_ABBYY_PATH.exists() else []


def write_placeholder(spec, start, end):
    spec_dir = SPEC_CORPUS_DIR / spec
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_json = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "spec": spec,
        "rangeStart": start,
        "rangeEnd": end,
        "pages": [],
        "placeholder": True,
        "notes": "Missing source text. Placeholder created from TOC.",
    }
    (spec_dir / "spec.json").write_text(json.dumps(spec_json, indent=2), encoding="utf-8")
    spec_txt = (
        "PLACEHOLDER: Missing spec corpus text.\n"
        f"Spec: {spec}\n"
        f"RangeStart: {start}\n"
        f"RangeEnd: {end}\n"
        "Source: TOC only\n"
    )
    (spec_dir / "spec.txt").write_text(spec_txt, encoding="utf-8")


def main():
    toc_index = load_json(TOC_INDEX_PATH, default={})
    toc_map = build_toc_map(toc_index)
    for toc_path in load_abbyy_toc_paths():
        if not toc_path.exists():
            continue
        abbyy_toc = load_json(toc_path, default={})
        merge_abbyy_toc(toc_map, abbyy_toc)
    toc_specs = set(toc_map.keys())

    spec_index = load_json(SPEC_INDEX_PATH, default=[])
    corpus_specs = {spec_key(entry.get("spec", "")) for entry in spec_index if entry.get("spec")}

    missing = sorted(toc_specs - corpus_specs)
    extra = sorted(corpus_specs - toc_specs)

    placeholders = []
    for spec in missing:
        info = toc_map.get(spec, {})
        start = info.get("start")
        end = info.get("end")
        write_placeholder(spec, start, end)
        placeholders.append(spec)
        spec_index.append(
            {
                "spec": spec,
                "rangeStart": start,
                "rangeEnd": end,
                "pageCount": 0,
                "path": f"spec_corpus\\{spec}\\spec.json",
                "placeholder": True,
            }
        )

    if placeholders:
        spec_index = sorted(
            spec_index,
            key=lambda entry: (
                entry.get("rangeStart") or 0,
                entry.get("spec") or "",
            ),
        )
        SPEC_INDEX_PATH.write_text(json.dumps(spec_index, indent=2), encoding="utf-8")

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "tocSpecs": len(toc_specs),
            "corpusSpecs": len(corpus_specs),
            "missingSpecs": len(missing),
            "extraSpecs": len(extra),
            "placeholdersCreated": len(placeholders),
        },
        "missingSpecs": missing,
        "extraSpecs": extra,
        "placeholders": placeholders,
    }
    OUTPUT_LOG.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Spec corpus TOC audit complete.")


if __name__ == "__main__":
    main()
