import argparse
import json
from datetime import datetime
from pathlib import Path


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


def build_boundary_set(boundary_path: Path) -> set[tuple[int, int]]:
    if not boundary_path.exists():
        return set()
    data = load_json(boundary_path)
    boundary = set()
    for entry in data.get("candidates", []):
        page = entry.get("page")
        idx = entry.get("chunkIndex")
        if page is not None and idx is not None:
            boundary.add((page, idx))
    return boundary


def build_page_lookup(spec_corpus_root: Path) -> dict[int, dict]:
    lookup = {}
    if not spec_corpus_root.exists():
        return lookup
    for spec_dir in spec_corpus_root.iterdir():
        if not spec_dir.is_dir():
            continue
        spec_path = spec_dir / "spec.json"
        if not spec_path.exists():
            continue
        spec_data = load_json(spec_path)
        spec = spec_data.get("spec") or spec_dir.name
        for page in spec_data.get("pages", []):
            page_idx = page.get("globalPageIndex")
            if isinstance(page_idx, int):
                entry = dict(page)
                entry["spec"] = spec
                lookup[page_idx] = entry
    return lookup


def issue_summary(diff_class: str, source_pattern: str) -> str:
    if diff_class == "true_missing":
        summary = "Other sources do not contain this chunk; confirm correct placement or provide the correct text."
    elif diff_class == "numeric":
        summary = "Sources disagree on numeric values or units; verify the correct numbers/units."
    elif diff_class == "modal":
        summary = "Sources disagree on modal verbs (shall/should/may); confirm the correct verb."
    elif diff_class == "structural":
        summary = "Sources differ in wording/structure; confirm the correct phrasing."
    else:
        summary = "Sources differ; confirm the correct text."

    if source_pattern and "boundary_truncation" in source_pattern:
        summary += " Possible page boundary/truncation; check adjacent page(s) for continuation."
    elif source_pattern and "source_absent" in source_pattern:
        summary += " Present in only one source; verify against the PDF."
    return summary


def build_section(label: str, top_groups: Path, collapse_map: Path, boundary_set: set[tuple[int, int]], spec_corpus_root: Path) -> list[str]:
    lines = []
    lines.append(f"[{label}]")
    if not top_groups.exists() or not collapse_map.exists():
        lines.append("  Missing input files.")
        lines.append("")
        return lines
    top_payload = load_json(top_groups)
    collapse_lookup = build_collapse_lookup(load_json(collapse_map))
    page_lookup = build_page_lookup(spec_corpus_root)

    lines.append(f"  Top N: {top_payload.get('topN')}, groups listed: {len(top_payload.get('groups', []))}")
    lines.append("")

    for group in top_payload.get("groups", []):
        rep = group.get("representativeChunk", {})
        rep_page = rep.get("page")
        rep_index = rep.get("chunkIndex")
        if rep_page is None or rep_index is None:
            continue
        if (rep_page, rep_index) in boundary_set:
            continue

        key = (group.get("subsection"), group.get("diffClass"), group.get("patternKey"), rep_page, rep_index)
        collapse_group = collapse_lookup.get(key, {})
        spec = collapse_group.get("spec", "unknown")

        footer_page = None
        source_pdf = None
        source_page_number = None

        page_entry = page_lookup.get(rep_page)
        if page_entry:
            spec = page_entry.get("spec", spec)
            source_pdf = page_entry.get("sourcePdf")
            source_page_number = page_entry.get("sourcePageNumber")
            footer_page = page_entry.get("footerPageNumber")
        elif spec != "unknown":
            spec_path = spec_corpus_root / spec / "spec.json"
            if spec_path.exists():
                spec_data = load_json(spec_path)
                for page in spec_data.get("pages", []):
                    if page.get("globalPageIndex") == rep_page:
                        source_pdf = page.get("sourcePdf")
                        source_page_number = page.get("sourcePageNumber")
                        footer_page = page.get("footerPageNumber")
                        break

        summary = issue_summary(group.get("diffClass"), group.get("patternKey"))

        lines.append(f"- group_id: {group.get('groupId')}")
        lines.append(f"  spec: {spec}")
        lines.append(f"  diff_class: {group.get('diffClass')}")
        lines.append(f"  source_pattern: {group.get('patternKey')}")
        lines.append(f"  representative_chunk: page-{rep_page:04d}:{rep_index}")
        if source_pdf:
            lines.append(f"  source_pdf: {source_pdf}")
        if source_page_number is not None:
            lines.append(f"  source_page_number: {source_page_number}")
        if footer_page is not None:
            lines.append(f"  footer_page_number: {footer_page}")
        lines.append(f"  issue_summary: {summary}")
        lines.append("  your_correction_or_notes:")
        lines.append("    ")
        lines.append("")

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a plain-English review list from top review groups."
    )
    parser.add_argument(
        "--part",
        action="append",
        default=[],
        help="Part spec: label|topGroups|collapseMap|specCorpusRoot",
    )
    parser.add_argument("--boundary", help="Path to boundary_candidates.json to exclude.")
    parser.add_argument("--out", required=True, help="Output text file path.")
    args = parser.parse_args()

    boundary_set = build_boundary_set(Path(args.boundary)) if args.boundary else set()
    header_note = "intrusions excluded" if args.boundary else "intrusions included (no boundary file provided)"

    lines = []
    lines.append(f"Review List: Plain-English Issues ({header_note})")
    lines.append(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("")

    for part_spec in args.part:
        label, top_groups, collapse_map, spec_corpus_root = part_spec.split("|", 3)
        lines.extend(
            build_section(
                label,
                Path(top_groups).resolve(),
                Path(collapse_map).resolve(),
                boundary_set,
                Path(spec_corpus_root).resolve(),
            )
        )

    out_path = Path(args.out).resolve()
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
