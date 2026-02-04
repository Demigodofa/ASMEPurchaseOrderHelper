import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF)-\d+[A-Z]?M?)\b", re.IGNORECASE)
DROP_RE = re.compile(
    r"\b(disregard|ignore|do not need|do not include|not needed|roman numeral|roman numerals|front matter)\b",
    re.IGNORECASE,
)
CONFIRM_RE = re.compile(r"\b(as-is|as is|correct|looks good|keep)\b", re.IGNORECASE)


def parse_worksheet(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    entries = []
    current = None
    in_notes = False
    note_lines = []

    def flush():
        nonlocal current, in_notes, note_lines
        if current:
            if note_lines:
                current["notes"] = " ".join(line.strip() for line in note_lines if line.strip())
            entries.append(current)
        current = None
        in_notes = False
        note_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- group_id:"):
            flush()
            current = {"group_id": stripped.split(":", 1)[1].strip()}
            continue
        if current is None:
            continue
        if stripped.startswith("spec:"):
            current["spec"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("representative_chunk:"):
            value = stripped.split(":", 1)[1].strip()
            current["representative_chunk"] = value
            match = re.search(r"page-(\d+):(\d+)", value)
            if match:
                current["page"] = int(match.group(1))
                current["chunkIndex"] = int(match.group(2))
            continue
        if stripped.startswith("source_pdf:"):
            current["source_pdf"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("source_page_number:"):
            try:
                current["source_page_number"] = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if stripped.startswith("footer_page_number:"):
            try:
                current["footer_page_number"] = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
            continue
        if stripped.startswith("your_correction_or_notes:"):
            in_notes = True
            note = stripped.split(":", 1)[1].strip()
            if note:
                note_lines.append(note)
            continue
        if stripped.startswith("- group_id:"):
            flush()
            current = {"group_id": stripped.split(":", 1)[1].strip()}
            continue
        if in_notes:
            if stripped.startswith("spec:") or stripped.startswith("subsection_id:"):
                in_notes = False
                continue
            note_lines.append(stripped)

    flush()
    return entries


def classify_entry(entry: dict) -> dict:
    notes = entry.get("notes", "") or ""
    notes_lower = notes.lower()
    specs = [match.group("spec").upper() for match in SPEC_RE.finditer(notes)]
    unique_specs = []
    for spec in specs:
        if spec not in unique_specs:
            unique_specs.append(spec)
    # Normalize SA-480M -> SA-480 when both exist.
    normalized_specs = []
    for spec in unique_specs:
        if spec.endswith("M") and spec[:-1] in unique_specs:
            spec = spec[:-1]
        if spec not in normalized_specs:
            normalized_specs.append(spec)

    action = "needs_manual_mapping"
    target_spec = None
    reason = ""

    if DROP_RE.search(notes_lower):
        action = "drop_page"
        reason = "note indicates non-essential/roman numeral content"
    elif CONFIRM_RE.search(notes_lower):
        action = "confirm_current"
        reason = "note indicates current placement is acceptable"
    elif len(normalized_specs) == 1:
        if entry.get("spec") and normalized_specs[0] != entry.get("spec"):
            action = "move_to_spec"
            target_spec = normalized_specs[0]
            reason = "note identifies different spec"
        else:
            action = "confirm_current"
            reason = "note repeats current spec"
    elif len(normalized_specs) > 1:
        action = "needs_manual_mapping"
        reason = "multiple specs mentioned in notes"

    entry["action"] = action
    entry["target_spec"] = target_spec
    entry["reason"] = reason
    entry["mentioned_specs"] = normalized_specs
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a boundary fix list from review worksheet notes."
    )
    parser.add_argument("--worksheet", required=True, help="Path to annotated review worksheet.")
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument("--csv", help="Optional CSV output path.")
    args = parser.parse_args()

    entries = parse_worksheet(Path(args.worksheet).resolve())
    annotated = [classify_entry(entry) for entry in entries if entry.get("notes")]

    output = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "worksheet": str(Path(args.worksheet).resolve()),
        "entries": annotated,
    }
    Path(args.out).write_text(json.dumps(output, indent=2), encoding="utf-8")

    if args.csv:
        csv_path = Path(args.csv)
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "group_id",
                    "spec",
                    "action",
                    "target_spec",
                    "reason",
                    "page",
                    "chunkIndex",
                    "source_pdf",
                    "source_page_number",
                    "footer_page_number",
                    "notes",
                    "mentioned_specs",
                ]
            )
            for entry in annotated:
                writer.writerow(
                    [
                        entry.get("group_id"),
                        entry.get("spec"),
                        entry.get("action"),
                        entry.get("target_spec"),
                        entry.get("reason"),
                        entry.get("page"),
                        entry.get("chunkIndex"),
                        entry.get("source_pdf"),
                        entry.get("source_page_number"),
                        entry.get("footer_page_number"),
                        entry.get("notes"),
                        ",".join(entry.get("mentioned_specs", [])),
                    ]
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
