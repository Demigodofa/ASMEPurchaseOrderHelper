import json
import os
import pathlib
import re
from datetime import datetime, timezone

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "sectionII_partA_data_digitized"
DEFAULT_DOCX_PATH = DATA / "ABBYY Scans" / "2025 OCR SECT II PART A BEGINNING TO SA-4501.docx"


def slugify(value):
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower() or "abbyy_docx"


DOCX_ENV = os.environ.get("ABBYY_DOCX_PATH")
DOCX_PATH = pathlib.Path(DOCX_ENV) if DOCX_ENV else DEFAULT_DOCX_PATH
OUTPUT_ENV = os.environ.get("ABBYY_DOCX_OUTPUT")
if OUTPUT_ENV:
    OUTPUT_DIR = DATA / OUTPUT_ENV
elif DOCX_ENV:
    OUTPUT_DIR = DATA / f"abbyy_docx_{slugify(DOCX_PATH.stem)}"
else:
    OUTPUT_DIR = DATA / "abbyy_docx"
PAGES_DIR = OUTPUT_DIR / "pages"
TABLES_DIR = OUTPUT_DIR / "tables"
MANIFEST_PATH = OUTPUT_DIR / "abbyy_docx_manifest.json"


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


def write_table_files(page_index, tables):
    if not tables:
        return 0
    tsv_path = TABLES_DIR / f"page-{page_index:04d}.tsv"
    md_path = TABLES_DIR / f"page-{page_index:04d}.md"
    tsv_lines = []
    md_lines = []
    for table in tables:
        for row in table:
            tsv_lines.append("\t".join(row))
            md_lines.append("| " + " | ".join(row) + " |")
        tsv_lines.append("")
        md_lines.append("")
    tsv_path.write_text("\n".join(tsv_lines).rstrip() + "\n", encoding="utf-8")
    md_path.write_text("\n".join(md_lines).rstrip() + "\n", encoding="utf-8")
    return len(tables)


def main():
    if not DOCX_PATH.exists():
        raise FileNotFoundError(f"DOCX not found: {DOCX_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    doc = Document(DOCX_PATH)
    body = doc._element.body
    pages = []
    current_lines = []
    current_tables = []

    for child in body.iterchildren():
        if child.tag.endswith("p"):
            text = paragraph_text(child)
            if text:
                current_lines.append(text)
            if paragraph_has_section_break(child):
                pages.append((current_lines, current_tables))
                current_lines = []
                current_tables = []
        elif child.tag.endswith("tbl"):
            rows = table_rows(child, doc)
            if rows:
                current_tables.append(rows)
                for row in rows:
                    current_lines.append("\t".join(row))

    if current_lines or current_tables:
        pages.append((current_lines, current_tables))

    manifest_pages = []
    table_pages = 0
    for idx, (lines, tables) in enumerate(pages, start=1):
        text = "\n".join(lines).strip()
        page_path = PAGES_DIR / f"page-{idx:04d}.txt"
        page_path.write_text(text + "\n" if text else "", encoding="utf-8")
        table_count = write_table_files(idx, tables)
        if table_count:
            table_pages += 1
        manifest_pages.append(
            {
                "abbyyPageIndex": idx,
                "textPath": str(page_path.relative_to(DATA)),
                "textLength": len(text),
                "tableCount": table_count,
            }
        )

    manifest = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "docxPath": str(DOCX_PATH),
            "pages": len(manifest_pages),
            "tablePages": table_pages,
        },
        "pages": manifest_pages,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("ABBYY DOCX pass A0 complete.")


if __name__ == "__main__":
    main()
