import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

from chunk_lock_utils import segment_text_with_separators
from freeze_guard import ensure_not_frozen


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def normalize_decision(value: str | None) -> str:
    if not value:
        return "defer"
    lowered = value.strip().lower()
    return lowered if lowered in {"approve", "reject", "defer"} else "defer"


def select_variant(chunk: dict, diff_class: str) -> dict | None:
    candidates = [
        variant
        for variant in chunk.get("variants", [])
        if variant.get("class") == diff_class
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (item.get("sourceCount", 0), len(item.get("text", ""))),
        reverse=True,
    )
    return candidates[0]


def compute_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def apply_part(part_spec: str) -> dict:
    parts = part_spec.split("|")
    if len(parts) != 7:
        raise ValueError("Part spec must be label|templates|collapse|classification|base|out|lockSummary")
    label, templates_path, collapse_path, classification_dir, base_dir, out_dir, lock_summary_path = parts

    templates = load_json(Path(templates_path))
    collapse = load_json(Path(collapse_path))
    classification_root = Path(classification_dir).resolve()
    base_root = Path(base_dir).resolve()
    out_root = Path(out_dir).resolve()
    lock_summary = load_json(Path(lock_summary_path)) if lock_summary_path else None

    approved_groups = []
    for template in templates.get("templates", []):
        if normalize_decision(template.get("decision")) == "approve":
            approved_groups.append(template)

    if out_root.exists():
        shutil.rmtree(out_root)
    shutil.copytree(base_root, out_root)

    chunk_lookup = {}
    chunk_counts = {}
    for page_path in classification_root.joinpath("pages").glob("page-*.json"):
        payload = load_json(page_path)
        page = payload.get("globalPageIndex")
        chunks = payload.get("chunks", [])
        chunk_counts[page] = len(chunks)
        for idx, chunk in enumerate(chunks):
            chunk_lookup[(page, idx)] = chunk

    collapse_lookup = {}
    for group in collapse.get("groups", []):
        rep = group.get("representativeChunk", {})
        key = (
            group.get("subsection"),
            group.get("diffClass"),
            group.get("patternKey"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        collapse_lookup[key] = group

    changes_by_page = {}
    applied_log = []
    skipped_chunks = 0
    skipped_pages = 0

    for template in approved_groups:
        rep = template.get("representative_chunk", {})
        key = (
            template.get("subsection_id"),
            template.get("diff_class"),
            template.get("source_presence_pattern"),
            rep.get("page"),
            rep.get("chunkIndex"),
        )
        group = collapse_lookup.get(key)
        if not group:
            continue
        affected = []
        for chunk_ref in group.get("chunks", []):
            page = chunk_ref.get("page")
            idx = chunk_ref.get("chunkIndex")
            chunk = chunk_lookup.get((page, idx))
            if not chunk or chunk.get("locked"):
                skipped_chunks += 1
                continue
            variant = select_variant(chunk, group.get("diffClass"))
            if not variant:
                skipped_chunks += 1
                continue
            changes_by_page.setdefault(page, {})[idx] = {
                "text": variant.get("text", ""),
                "class": variant.get("class"),
                "sources": variant.get("sources", []),
            }
            affected.append({"page": page, "chunkIndex": idx})

        applied_log.append(
            {
                "group_id": template.get("group_id"),
                "representative_chunk": rep,
                "affected_chunks": affected,
                "reviewer_id": template.get("reviewer_id"),
                "decision_timestamp": template.get("decision_timestamp"),
                "diff_class": group.get("diffClass"),
                "pattern_key": group.get("patternKey"),
            }
        )

    for page, updates in changes_by_page.items():
        page_path = out_root / "pages" / f"page-{page:04d}.txt"
        if not page_path.exists():
            skipped_pages += 1
            continue
        text = page_path.read_text(encoding="utf-8", errors="ignore")
        segmented = segment_text_with_separators(text)
        segments = segmented["segments"]
        if page not in chunk_counts or chunk_counts[page] != len(segments):
            skipped_pages += 1
            continue
        for idx, segment in enumerate(segments):
            if idx in updates:
                segment["text"] = updates[idx]["text"]
        rebuilt = segmented["leading"] + "".join(
            segment["text"] + segment["sep"] for segment in segments
        )
        page_path.write_text(rebuilt, encoding="utf-8")

    combined_lines = []
    for page_path in sorted((out_root / "pages").glob("page-*.txt")):
        page_number = int(page_path.stem.replace("page-", ""))
        text = page_path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            combined_lines.append(f"=== Page {page_number} ===")
            combined_lines.append(text)
    combined_path = out_root / "combined.txt"
    combined_path.write_text("\n\n".join(combined_lines), encoding="utf-8")

    content_hash = compute_hash(combined_path)

    return {
        "label": label,
        "output": str(out_root),
        "contentHash": content_hash,
        "lockSummary": lock_summary,
        "appliedApprovals": applied_log,
        "approvedGroupCount": len(approved_groups),
        "appliedChunkCount": sum(len(item["affected_chunks"]) for item in applied_log),
        "skippedChunks": skipped_chunks,
        "skippedPages": skipped_pages,
    }


def main() -> int:
    ensure_not_frozen()
    parser = argparse.ArgumentParser(
        description="Apply approved review groups and publish frozen corpus."
    )
    parser.add_argument(
        "--part",
        action="append",
        default=[],
        help="Part spec: label|templates|collapse|classification|base|out|lockSummary",
    )
    parser.add_argument(
        "--freeze-manifest",
        required=True,
        help="Output freeze manifest path.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.freeze_manifest).resolve()
    results = []
    for part_spec in args.part:
        results.append(apply_part(part_spec))

    manifest = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "frozen": True,
        "freezeManifest": str(manifest_path),
        "corpora": results,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
