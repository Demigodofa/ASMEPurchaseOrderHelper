import json
import os
import re
from datetime import datetime, timezone

from pypdf import PdfReader


def resolve_pdf_files(config_path):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    paths = config.get("Paths", {})
    pdf_files = [p for p in paths.get("PdfFiles", []) if p and p.strip()]

    if pdf_files:
        existing = []
        for path in pdf_files:
            if os.path.exists(path):
                existing.append(path)
            else:
                print(f"Warning: missing PDF file: {path}")
        if not existing:
            raise FileNotFoundError("No PDF files found to digitize.")
        return existing

    root = paths.get("PdfSourceRoot")
    if not root:
        root = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(root):
        raise FileNotFoundError(f"PDF source root not found: {root}")

    pdf_files = []
    for name in os.listdir(root):
        if not name.lower().endswith(".pdf"):
            continue
        if "sect ii" not in name.lower():
            continue
        if "part a" not in name.lower():
            continue
        if "part b" in name.lower():
            continue
        pdf_files.append(os.path.join(root, name))

    if not pdf_files:
        raise FileNotFoundError("No PDF files found to digitize.")

    return pdf_files


def split_table_rows(lines):
    tables = []
    current = []
    for line in lines:
        trimmed = line.strip()
        if not trimmed:
            if current:
                tables.append({"rows": current})
                current = []
            continue

        cols = [c.strip() for c in re.split(r"\s{2,}", trimmed) if c.strip()]
        if len(cols) >= 3:
            current.append(cols)
        else:
            if current:
                tables.append({"rows": current})
                current = []
    if current:
        tables.append({"rows": current})
    return tables


def extract_notes(lines):
    notes = []
    for line in lines:
        trimmed = line.strip()
        if re.match(r"^(NOTE|NOTES|Note)\b", trimmed):
            notes.append(trimmed)
    return notes


def write_table_files(base_name, tables_dir, tables, notes):
    md_path = os.path.join(tables_dir, f"{base_name}.md")
    tsv_path = os.path.join(tables_dir, f"{base_name}.tsv")

    if not tables:
        with open(md_path, "w", encoding="utf-8") as handle:
            handle.write("No tables detected in pass 1.\n")
        with open(tsv_path, "w", encoding="utf-8") as handle:
            handle.write("")
        return

    md_lines = []
    tsv_lines = []
    table_index = 1
    for table in tables:
        md_lines.append(f"## Table {table_index}")
        rows = table.get("rows", [])
        if rows:
            header = rows[0]
            md_lines.append("| " + " | ".join(header) + " |")
            md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
            for row in rows[1:]:
                md_lines.append("| " + " | ".join(row) + " |")
            for row in rows:
                tsv_lines.append("\t".join(row))
        md_lines.append("")
        table_index += 1

    if notes:
        md_lines.append("## Notes")
        for note in notes:
            md_lines.append(f"- {note}")

    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(md_lines).rstrip() + "\n")
    with open(tsv_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(tsv_lines).rstrip() + "\n")


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    config_path = os.path.join(repo_root, "PoApp.Ingest.Cli", "appsettings.json")
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    pages_dir = os.path.join(output_root, "pages")
    tables_dir = os.path.join(output_root, "tables")

    os.makedirs(pages_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)

    pdf_files = resolve_pdf_files(config_path)

    manifest = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "sourcePdfs": pdf_files,
        "outputRoot": output_root,
        "pages": [],
    }

    global_index = 1
    for pdf_path in pdf_files:
        print(f"Digitizing: {pdf_path}")
        reader = PdfReader(pdf_path)
        for page_index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            lines = text.replace("\r\n", "\n").split("\n")
            tables = split_table_rows(lines)
            notes = extract_notes(lines)

            base_name = f"page-{global_index:04d}"
            json_path = os.path.join(pages_dir, f"{base_name}.json")
            txt_path = os.path.join(pages_dir, f"{base_name}.txt")

            page_json = {
                "sourcePdf": os.path.basename(pdf_path),
                "sourcePageNumber": page_index,
                "globalPageIndex": global_index,
                "width": float(page.mediabox.width),
                "height": float(page.mediabox.height),
                "text": text,
                "words": [],
                "tableCount": len(tables),
                "noteCount": len(notes),
            }

            with open(json_path, "w", encoding="utf-8") as handle:
                json.dump(page_json, handle, indent=2)
            with open(txt_path, "w", encoding="utf-8") as handle:
                handle.write(text)

            write_table_files(base_name, tables_dir, tables, notes)

            manifest["pages"].append(
                {
                    "globalPageIndex": global_index,
                    "sourcePdf": os.path.basename(pdf_path),
                    "sourcePageNumber": page_index,
                    "json": f"pages/{base_name}.json",
                    "text": f"pages/{base_name}.txt",
                    "tablesMd": f"tables/{base_name}.md",
                    "tablesTsv": f"tables/{base_name}.tsv",
                    "tableCount": len(tables),
                }
            )

            global_index += 1

    manifest_path = os.path.join(output_root, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"Digitization complete. Output: {output_root}")


if __name__ == "__main__":
    main()
