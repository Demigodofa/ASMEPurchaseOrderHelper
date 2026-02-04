import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def load_index(root: Path) -> list[dict]:
    index_path = root / "spec_corpus_index.json"
    if not index_path.exists():
        return []
    return json.loads(index_path.read_text(encoding="utf-8", errors="ignore"))


def load_spec_entry(spec_dir: Path) -> dict | None:
    spec_json = spec_dir / "spec.json"
    if not spec_json.exists():
        return None
    data = json.loads(spec_json.read_text(encoding="utf-8", errors="ignore"))
    spec = data.get("spec")
    pages = data.get("pages", [])
    if not spec or not pages:
        return None
    pages_sorted = sorted(pages, key=lambda p: p.get("globalPageIndex", 0))
    return {
        "spec": spec,
        "rangeStart": pages_sorted[0].get("globalPageIndex"),
        "rangeEnd": pages_sorted[-1].get("globalPageIndex"),
        "pageCount": len(pages_sorted),
        "path": str((spec_dir / "spec.json").name),
    }


def copy_spec(spec: str, source_root: Path, out_root: Path) -> None:
    src = source_root / spec
    dest = out_root / spec
    if not src.exists():
        return
    if dest.exists():
        return
    shutil.copytree(src, dest)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge two spec_corpus roots (primary wins for shared specs)."
    )
    parser.add_argument("--primary", required=True, help="Primary spec_corpus root.")
    parser.add_argument("--secondary", required=True, help="Secondary spec_corpus root.")
    parser.add_argument("--out", required=True, help="Output spec_corpus root.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow writing into an existing output directory.",
    )
    args = parser.parse_args()

    primary_root = Path(args.primary).resolve()
    secondary_root = Path(args.secondary).resolve()
    out_root = Path(args.out).resolve()

    out_root.mkdir(parents=True, exist_ok=True)
    if not args.force and any(out_root.iterdir()):
        raise SystemExit(f"Output directory is not empty: {out_root}")

    primary_index = load_index(primary_root)
    secondary_index = load_index(secondary_root)

    primary_specs = [entry.get("spec") for entry in primary_index if entry.get("spec")]
    secondary_specs = [entry.get("spec") for entry in secondary_index if entry.get("spec")]

    primary_set = set(primary_specs)
    secondary_set = set(secondary_specs)

    for spec in primary_specs:
        copy_spec(spec, primary_root, out_root)

    for spec in secondary_specs:
        if spec in primary_set:
            continue
        copy_spec(spec, secondary_root, out_root)

    output_index = []
    for spec in primary_specs + [s for s in secondary_specs if s not in primary_set]:
        spec_dir = out_root / spec
        entry = load_spec_entry(spec_dir)
        if not entry:
            continue
        entry["path"] = str(Path(spec) / "spec.json")
        output_index.append(entry)

    output_index_path = out_root / "spec_corpus_index.json"
    output_index_path.write_text(json.dumps(output_index, indent=2), encoding="utf-8")

    manifest = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "primary": str(primary_root),
        "secondary": str(secondary_root),
        "specCount": len(output_index),
        "output": str(out_root),
    }
    (out_root / "merge_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
