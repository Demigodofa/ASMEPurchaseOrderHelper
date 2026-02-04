import argparse
import json
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table


def paragraph_text(paragraph):
    text = "".join(node.text or "" for node in paragraph.iter(qn("w:t")))
    return " ".join(text.split())


def paragraph_has_section_break(paragraph):
    ppr = paragraph.find(qn("w:pPr"))
    if ppr is None:
        return False
    return ppr.find(qn("w:sectPr")) is not None


def normalize_cell(text):
    return " ".join(text.split())


def table_rows(table_element, document):
    table = Table(table_element, document)
    rows = []
    for row in table.rows:
        cells = [normalize_cell(cell.text) for cell in row.cells]
        if any(cells):
            rows.append(cells)
    return rows


def alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    alpha = sum(1 for ch in text if ch.isalpha())
    total = sum(1 for ch in text if not ch.isspace())
    if total == 0:
        return 0.0
    return alpha / total


def detect_page_number(text: str) -> int | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    candidates = []
    scan_lines = lines[:8] + lines[-8:]
    for line in scan_lines:
        if line.isdigit() and len(line) <= 4:
            candidates.append(int(line))
            continue
        lowered = line.lower()
        if "page" in lowered:
            parts = lowered.split()
            for part in parts:
                if part.isdigit():
                    candidates.append(int(part))
    for value in candidates:
        if 1 <= value <= 5000:
            return value
    return None


def build_docx_packets(docx_path: Path, output_root: Path, label: str) -> None:
    pages_dir = output_root / "pages"
    pdf_text_dir = output_root / "pdf_text"
    pages_dir.mkdir(parents=True, exist_ok=True)
    pdf_text_dir.mkdir(parents=True, exist_ok=True)

    doc = Document(docx_path)
    body = doc._element.body
    pages = []
    current_lines = []

    for child in body.iterchildren():
        if child.tag.endswith("p"):
            text = paragraph_text(child)
            if text:
                current_lines.append(text)
            if paragraph_has_section_break(child):
                pages.append(current_lines)
                current_lines = []
        elif child.tag.endswith("tbl"):
            rows = table_rows(child, doc)
            if rows:
                for row in rows:
                    current_lines.append("\t".join(row))

    if current_lines:
        pages.append(current_lines)

    manifest = {
        "sourceLabel": label,
        "sourceDocx": str(docx_path),
        "pageCount": len(pages),
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "pagesDir": "pages",
        "pdfTextDir": "pdf_text",
    }
    (output_root / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    for idx, lines in enumerate(pages, start=1):
        text = "\n".join(lines).strip()
        page_text_path = pdf_text_dir / f"page-{idx:04d}.txt"
        page_text_path.write_text(text + "\n" if text else "", encoding="utf-8")

        text_length = len(text)
        alpha = round(alpha_ratio(text), 4)
        low_conf = text_length < 300 or alpha < 0.2
        detected = detect_page_number(text)

        page_payload = {
            "pageNumber": idx,
            "sourceLabel": label,
            "sourceDocx": str(docx_path),
            "pdfTextPath": str(page_text_path.relative_to(output_root)),
            "pdfTextLength": text_length,
            "pdfAlphaRatio": alpha,
            "lowConfidenceCandidate": low_conf,
            "detectedPageNumber": detected,
            "detectedPageNumberPdf": detected,
        }
        (pages_dir / f"page-{idx:04d}.json").write_text(
            json.dumps(page_payload, indent=2), encoding="utf-8"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build page packets from an ABBYY DOCX.")
    parser.add_argument("--docx", required=True, help="Path to ABBYY docx.")
    parser.add_argument("--out", required=True, help="Output root folder.")
    parser.add_argument("--label", required=True, help="Source label used in metadata.")
    args = parser.parse_args()

    docx_path = Path(args.docx).resolve()
    output_root = Path(args.out).resolve()
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX not found: {docx_path}")

    build_docx_packets(docx_path, output_root, args.label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
