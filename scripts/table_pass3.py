import json
import os
from datetime import datetime, timezone

import tabula


JAVA_HOME_DEFAULT = r"C:\Program Files\Eclipse Adoptium\jre-17.0.17.10-hotspot"


def ensure_java():
    if "JAVA_HOME" not in os.environ and os.path.isdir(JAVA_HOME_DEFAULT):
        os.environ["JAVA_HOME"] = JAVA_HOME_DEFAULT
        os.environ["PATH"] = os.path.join(JAVA_HOME_DEFAULT, "bin") + os.pathsep + os.environ.get("PATH", "")
    if "JAVA_TOOL_OPTIONS" not in os.environ:
        os.environ["JAVA_TOOL_OPTIONS"] = ""


def load_manifest(output_root):
    manifest_path = os.path.join(output_root, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def likely_table_page(text):
    if not text:
        return False
    if "Table" in text or "TABLE" in text:
        return True
    lines = text.replace("\r\n", "\n").split("\n")
    spaced = 0
    for line in lines:
        if "  " in line and len(line.split()) >= 6:
            spaced += 1
        if spaced >= 6:
            return True
    return False


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    tables_dir = os.path.join(output_root, "tables_tabula")
    os.makedirs(tables_dir, exist_ok=True)

    ensure_java()
    manifest = load_manifest(output_root)

    pdf_paths = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}
    font_cache = os.path.join(output_root, "pdfbox-fontcache")
    os.makedirs(font_cache, exist_ok=True)
    os.environ["JAVA_TOOL_OPTIONS"] = os.environ["JAVA_TOOL_OPTIONS"] + f" -Dpdfbox.fontcache={font_cache}"
    table_log = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "processedPages": 0,
        "tablePages": 0,
    }

    for page_entry in manifest.get("pages", []):
        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        text = page_json.get("text", "")
        if not likely_table_page(text):
            continue

        source_pdf = page_json.get("sourcePdf")
        source_page = page_json.get("sourcePageNumber", 1)
        pdf_path = pdf_paths.get(source_pdf)
        if not pdf_path or not os.path.exists(pdf_path):
            continue

        try:
            tables = tabula.read_pdf(pdf_path, pages=source_page, multiple_tables=True)
        except Exception:
            tables = []

        base_name = f"page-{page_json.get('globalPageIndex', 0):04d}"
        json_out = os.path.join(tables_dir, f"{base_name}.json")
        csv_out = os.path.join(tables_dir, f"{base_name}.csv")

        table_payload = []
        csv_lines = []
        for table in tables:
            rows = table.fillna("").astype(str).values.tolist()
            table_payload.append({"rows": rows})
            for row in rows:
                csv_lines.append(",".join(row))
            csv_lines.append("")

        with open(json_out, "w", encoding="utf-8") as handle:
            json.dump(table_payload, handle, indent=2)
        with open(csv_out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(csv_lines).rstrip() + "\n")

        page_json["tabulaTablesPath"] = f"tables_tabula/{base_name}.json"
        page_json["tabulaTablesCsv"] = f"tables_tabula/{base_name}.csv"
        page_json["tabulaTableCount"] = len(tables)

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        table_log["processedPages"] += 1
        if tables:
            table_log["tablePages"] += 1

    log_path = os.path.join(output_root, "table_pass3_log.json")
    with open(log_path, "w", encoding="utf-8") as handle:
        json.dump(table_log, handle, indent=2)

    print("Table pass complete.")


if __name__ == "__main__":
    main()
