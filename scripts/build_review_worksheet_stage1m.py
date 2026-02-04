import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

from chunk_lock_utils import chunk_text


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def build_collapse_lookup(collapse_map: dict) -> dict[tuple[str, str, str, int, int], dict]:
    lookup = {}
    for group in collapse_map.get("groups", []):
        rep = group.get("representativeChunk", {})
        key = (
            group.get("subsection"),
            group.get("diffClass"),
            group.get("patternKey"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        lookup[key] = group
    return lookup


def extract_chunk_text(page_path: Path, chunk_index: int) -> str:
    if not page_path.exists():
        return ""
    text = page_path.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_text(text)
    if chunk_index < 0 or chunk_index >= len(chunks):
        return ""
    return chunks[chunk_index].get("text", "").strip()


def load_page_map(manifest_path: Path) -> dict[int, dict]:
    manifest = load_json(manifest_path)
    mapping = {}
    for page in manifest.get("pages", []):
        mapping[page.get("globalPageIndex")] = page
    return mapping


def load_spec_ranges(spec_range_path: Path) -> tuple[dict[str, dict], dict[int, str]]:
    payload = load_json(spec_range_path)
    ranges = {}
    intrusions = {}
    for entry in payload.get("ranges", []):
        spec = entry.get("spec")
        start = entry.get("startGlobalPage")
        end = entry.get("endGlobalPage")
        if spec and start and end:
            ranges[spec] = {"start": start, "end": end}
        for intrusion in entry.get("intrusions", []):
            page = intrusion.get("globalPageIndex")
            detected = intrusion.get("detectedSpec")
            if page and detected:
                intrusions[int(page)] = detected
    return ranges, intrusions


def get_footer_map(spec_corpus_root: Path, spec: str, cache: dict[str, dict]) -> dict[int, int | None]:
    if spec in cache:
        return cache[spec]
    if spec == "unknown":
        cache[spec] = {}
        return cache[spec]
    spec_path = spec_corpus_root / spec / "spec.json"
    if not spec_path.exists():
        cache[spec] = {}
        return cache[spec]
    payload = load_json(spec_path)
    mapping = {}
    for page in payload.get("pages", []):
        mapping[page.get("globalPageIndex")] = page.get("footerPageNumber")
    cache[spec] = mapping
    return mapping


def build_section(
    label: str,
    top_groups_path: Path,
    collapse_path: Path,
    final_pages: Path,
    spec_corpus_root: Path,
    page_map: dict[int, dict],
    spec_ranges: dict[str, dict],
    intrusions: dict[int, str],
    footer_cache: dict[str, dict],
    boundary_candidates: list[dict],
    exclude_intrusions: bool,
) -> list[str]:
    lines = []
    lines.append(f"[{label}]")
    if not top_groups_path.exists():
        lines.append(f"Missing top groups: {top_groups_path}")
        lines.append("")
        return lines
    if not collapse_path.exists():
        lines.append(f"Missing collapse map: {collapse_path}")
        lines.append("")
        return lines

    top_groups = load_json(top_groups_path)
    collapse_lookup = build_collapse_lookup(load_json(collapse_path))
    lines.append(f"Top N: {top_groups.get('topN')}, groups listed: {len(top_groups.get('groups', []))}")
    lines.append("")

    for group in top_groups.get("groups", []):
        rep = group.get("representativeChunk", {})
        key = (
            group.get("subsection"),
            group.get("diffClass"),
            group.get("patternKey"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        collapse = collapse_lookup.get(key)
        spec = collapse.get("spec") if collapse else "unknown"
        page = rep.get("page")
        chunk_index = rep.get("chunkIndex")
        page_path = final_pages / f"page-{page:04d}.txt" if page is not None else None
        chunk_text_value = extract_chunk_text(page_path, chunk_index) if page_path else ""
        spec_path = spec_corpus_root / spec / "spec.txt" if spec != "unknown" else None
        page_meta = page_map.get(page) if page is not None else None
        source_pdf = page_meta.get("sourcePdf") if page_meta else None
        source_page = page_meta.get("sourcePageNumber") if page_meta else None
        footer_map = get_footer_map(spec_corpus_root, spec, footer_cache)
        footer_page = footer_map.get(page)
        range_info = spec_ranges.get(spec)
        intrusion_spec = intrusions.get(page) if page is not None else None

        rep_id = f"page-{page:04d}:{chunk_index}" if page is not None else "unknown"
        if intrusion_spec and exclude_intrusions:
            likely_front_matter = False
            front_matter_reason = None
            if footer_page is None and source_page is not None and source_page <= 60:
                likely_front_matter = True
                front_matter_reason = "footer_page_number missing; early source_page_number (<=60)"
            boundary_candidates.append(
                {
                    "group_id": group.get("groupId"),
                    "spec": spec,
                    "intrusion_detected_spec": intrusion_spec,
                    "representative_chunk": rep_id,
                    "page": page,
                    "chunkIndex": chunk_index,
                    "source_pdf": source_pdf,
                    "source_page_number": source_page,
                    "footer_page_number": footer_page,
                    "likely_front_matter": likely_front_matter,
                    "front_matter_reason": front_matter_reason,
                    "toc_range": f"{range_info['start']}-{range_info['end']}" if range_info else None,
                    "final_best_text_page": str(page_path) if page_path else None,
                    "current_spec_path": str(spec_path) if spec_path else None,
                }
            )
            continue
        lines.append(f"- group_id: {group.get('groupId')}")
        lines.append(f"  spec: {spec}")
        lines.append(f"  subsection_id: {group.get('subsection')}")
        lines.append(f"  diff_class: {group.get('diffClass')}")
        lines.append(f"  source_pattern: {group.get('patternKey')}")
        lines.append(f"  group_size: {group.get('groupSize')}")
        lines.append(f"  representative_chunk: {rep_id}")
        if source_pdf:
            lines.append(f"  source_pdf: {source_pdf}")
        if source_page is not None:
            lines.append(f"  source_page_number: {source_page}")
        if footer_page is not None:
            lines.append(f"  footer_page_number: {footer_page}")
        if range_info:
            lines.append(f"  toc_range: {range_info['start']}-{range_info['end']}")
        if intrusion_spec:
            lines.append(f"  intrusion_detected_spec: {intrusion_spec}")
        if page_path:
            lines.append(f"  final_best_text_page: {page_path}")
        if spec_path:
            lines.append(f"  current_spec_path: {spec_path}")
        if chunk_text_value:
            lines.append("  current_chunk_text:")
            for line in chunk_text_value.splitlines():
                lines.append(f"    {line}")
        else:
            lines.append("  current_chunk_text: [unable to extract]")
        lines.append("  your_correction_or_notes:")
        lines.append("    ")
        lines.append("")

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a review worksheet with chunk text and locations."
    )
    parser.add_argument(
        "--part",
        action="append",
        default=[],
        help="Part spec: label|topGroups|collapseMap|finalBestTextPages|specCorpusRoot|manifest|specRange",
    )
    parser.add_argument("--out", required=True, help="Output text file path.")
    parser.add_argument(
        "--exclude-intrusions",
        action="store_true",
        help="Exclude intrusion-detected specs from the worksheet and emit boundary candidates.",
    )
    parser.add_argument("--boundary-out", help="Optional boundary candidates JSON output path.")
    parser.add_argument("--boundary-csv", help="Optional boundary candidates CSV output path.")
    args = parser.parse_args()

    output_lines = []
    output_lines.append("Review Worksheet: Top Review Groups")
    output_lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    output_lines.append("Notes: Fill in corrections or notes under each item.")
    output_lines.append("")

    boundary_candidates = []
    for part_spec in args.part:
        label, top_groups, collapse_map, final_pages, spec_corpus, manifest_path, spec_range_path = part_spec.split("|", 6)
        spec_ranges, intrusions = load_spec_ranges(Path(spec_range_path).resolve())
        footer_cache = {}
        output_lines.extend(
            build_section(
                label,
                Path(top_groups).resolve(),
                Path(collapse_map).resolve(),
                Path(final_pages).resolve(),
                Path(spec_corpus).resolve(),
                load_page_map(Path(manifest_path).resolve()),
                spec_ranges,
                intrusions,
                footer_cache,
                boundary_candidates,
                args.exclude_intrusions,
            )
        )

    out_path = Path(args.out).resolve()
    out_path.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    if args.boundary_out:
        boundary_path = Path(args.boundary_out).resolve()
        boundary_payload = {
            "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "candidates": boundary_candidates,
        }
        boundary_path.write_text(json.dumps(boundary_payload, indent=2), encoding="utf-8")
    if args.boundary_csv:
        csv_path = Path(args.boundary_csv).resolve()
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "group_id",
                    "spec",
                    "intrusion_detected_spec",
                    "representative_chunk",
                    "page",
                    "chunkIndex",
                    "source_pdf",
                    "source_page_number",
                    "footer_page_number",
                    "likely_front_matter",
                    "front_matter_reason",
                    "toc_range",
                    "final_best_text_page",
                    "current_spec_path",
                ]
            )
            for entry in boundary_candidates:
                writer.writerow(
                    [
                        entry.get("group_id"),
                        entry.get("spec"),
                        entry.get("intrusion_detected_spec"),
                        entry.get("representative_chunk"),
                        entry.get("page"),
                        entry.get("chunkIndex"),
                        entry.get("source_pdf"),
                        entry.get("source_page_number"),
                        entry.get("footer_page_number"),
                        entry.get("likely_front_matter"),
                        entry.get("front_matter_reason"),
                        entry.get("toc_range"),
                        entry.get("final_best_text_page"),
                        entry.get("current_spec_path"),
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
