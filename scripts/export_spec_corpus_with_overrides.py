import argparse
import json
import pathlib
import re
from datetime import datetime, timezone


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def extract_footer_page_number(text: str | None) -> int | None:
    if not text:
        return None
    lines = text.replace("\r\n", "\n").split("\n")
    footer_re = re.compile(r"^\d{1,4}$")
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        if footer_re.match(line):
            return int(line)
    return None


def build_page_to_spec(spec_corpus_root: pathlib.Path) -> tuple[dict[int, str], list[str]]:
    page_to_spec: dict[int, str] = {}
    spec_order: list[str] = []
    index_path = spec_corpus_root / "spec_corpus_index.json"
    if index_path.exists():
        index = load_json(index_path)
        spec_order = [entry["spec"] for entry in index]

    for spec_dir in spec_corpus_root.iterdir():
        if not spec_dir.is_dir():
            continue
        spec_json = spec_dir / "spec.json"
        if not spec_json.exists():
            continue
        data = load_json(spec_json)
        spec = data.get("spec")
        if not spec:
            continue
        if spec not in spec_order:
            spec_order.append(spec)
        for page in data.get("pages", []):
            idx = page.get("globalPageIndex")
            if isinstance(idx, int):
                page_to_spec[idx] = spec

    return page_to_spec, spec_order


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export spec corpus using best_text with page-level overrides."
    )
    parser.add_argument("--manifest", required=True, help="Path to manifest.json.")
    parser.add_argument("--best-text", required=True, help="Folder with best_text/pages.")
    parser.add_argument("--spec-corpus", required=True, help="Existing spec_corpus root.")
    parser.add_argument("--overrides", required=True, help="Boundary fix list (applied) JSON.")
    parser.add_argument("--out", required=True, help="Output spec_corpus folder.")
    parser.add_argument("--report", help="Optional overrides report JSON path.")
    parser.add_argument(
        "--data-root",
        required=False,
        help="Root folder for relative text paths (defaults to sectionII_partA_data_digitized).",
    )
    args = parser.parse_args()

    manifest = load_json(pathlib.Path(args.manifest))
    manifest_pages = {page["globalPageIndex"]: page for page in manifest.get("pages", [])}

    page_to_spec, spec_order = build_page_to_spec(pathlib.Path(args.spec_corpus))

    overrides = load_json(pathlib.Path(args.overrides))
    applied = []
    for entry in overrides.get("entries", []):
        action = entry.get("action")
        page = entry.get("page")
        if not isinstance(page, int):
            continue
        if action == "move_to_spec":
            target = entry.get("target_spec")
            if not target:
                continue
            from_spec = page_to_spec.get(page)
            page_to_spec[page] = target
            if target not in spec_order:
                spec_order.append(target)
            applied.append(
                {
                    "group_id": entry.get("group_id"),
                    "page": page,
                    "from_spec": from_spec,
                    "to_spec": target,
                    "reason": entry.get("override_reason") or entry.get("reason"),
                }
            )
        elif action == "drop_page":
            from_spec = page_to_spec.pop(page, None)
            applied.append(
                {
                    "group_id": entry.get("group_id"),
                    "page": page,
                    "from_spec": from_spec,
                    "to_spec": None,
                    "reason": entry.get("override_reason") or entry.get("reason"),
                }
            )

    spec_pages: dict[str, list[int]] = {}
    for page, spec in page_to_spec.items():
        spec_pages.setdefault(spec, []).append(page)

    best_text_dir = pathlib.Path(args.best_text).resolve()
    output_dir = pathlib.Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.data_root:
        data_root = pathlib.Path(args.data_root).resolve()
    else:
        data_root = best_text_dir
        if len(best_text_dir.parents) >= 4:
            data_root = best_text_dir.parents[3]

    output_index = []
    for spec in spec_order:
        pages = spec_pages.get(spec)
        if not pages:
            continue
        pages_sorted = sorted(pages)
        spec_dir = output_dir / spec
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_pages_payload = []
        combined_lines = []
        for idx in pages_sorted:
            page_meta = manifest_pages.get(idx)
            if not page_meta:
                continue
            text_path = best_text_dir / f"page-{idx:04d}.txt"
            text = text_path.read_text(encoding="utf-8", errors="ignore") if text_path.exists() else ""
            footer_page_number = extract_footer_page_number(text)
            spec_pages_payload.append(
                {
                    "globalPageIndex": idx,
                    "sourcePdf": page_meta.get("sourcePdf"),
                    "sourcePageNumber": page_meta.get("sourcePageNumber"),
                    "footerPageNumber": footer_page_number,
                    "textPath": str(text_path.relative_to(data_root)) if text_path.exists() else None,
                    "assets": {},
                }
            )
            if text:
                combined_lines.append(f"=== Page {idx} ===")
                combined_lines.append(text.strip())

        spec_json = {
            "createdUtc": datetime.now(timezone.utc).isoformat(),
            "spec": spec,
            "rangeStart": pages_sorted[0],
            "rangeEnd": pages_sorted[-1],
            "pages": spec_pages_payload,
        }
        (spec_dir / "spec.json").write_text(json.dumps(spec_json, indent=2), encoding="utf-8")
        (spec_dir / "spec.txt").write_text("\n\n".join(combined_lines), encoding="utf-8")

        output_index.append(
            {
                "spec": spec,
                "rangeStart": pages_sorted[0],
                "rangeEnd": pages_sorted[-1],
                "pageCount": len(spec_pages_payload),
                "path": str((spec_dir / "spec.json").relative_to(output_dir)),
            }
        )

    (output_dir / "spec_corpus_index.json").write_text(
        json.dumps(output_index, indent=2), encoding="utf-8"
    )

    if args.report:
        report_path = pathlib.Path(args.report)
        report = {
            "createdUtc": datetime.now(timezone.utc).isoformat(),
            "overrides": applied,
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Spec corpus export with overrides complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
