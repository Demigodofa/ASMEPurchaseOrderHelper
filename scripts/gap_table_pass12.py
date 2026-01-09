import json
import os
from datetime import datetime, timezone

import camelot


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    crossref_path = os.path.join(output_root, "crossref_pass9.json")
    manifest_path = os.path.join(output_root, "manifest.json")
    out_dir = os.path.join(output_root, "camelot_tables")
    os.makedirs(out_dir, exist_ok=True)

    with open(crossref_path, "r", encoding="utf-8") as handle:
        crossref = json.load(handle)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    page_map = {p.get("globalPageIndex"): p for p in manifest.get("pages", [])}
    pdf_map = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    gap_counts = {}
    for entry in crossref.get("tableRefGaps", []):
        gap_counts[entry["globalPageIndex"]] = gap_counts.get(entry["globalPageIndex"], 0) + 1
    for entry in crossref.get("noteRefGaps", []):
        gap_counts[entry["globalPageIndex"]] = gap_counts.get(entry["globalPageIndex"], 0) + 1

    top_pages = sorted(gap_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:20]

    report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "pagesProcessed": 0,
        "tablesFound": 0,
        "topPages": [],
    }

    for page_index, gap_count in top_pages:
        page_entry = page_map.get(page_index)
        if not page_entry:
            continue

        json_path = os.path.join(output_root, page_entry["json"])
        with open(json_path, "r", encoding="utf-8") as handle:
            page_json = json.load(handle)

        source_pdf = page_json.get("sourcePdf")
        source_page = page_json.get("sourcePageNumber")
        pdf_path = pdf_map.get(source_pdf)
        if not pdf_path or not source_page:
            continue

        tables = []
        for flavor in ("lattice", "stream"):
            try:
                tables = camelot.read_pdf(pdf_path, pages=str(source_page), flavor=flavor)
                if tables.n > 0:
                    break
            except Exception:
                continue

        base_name = f"page-{page_index:04d}"
        json_out = os.path.join(out_dir, f"{base_name}.json")
        csv_out = os.path.join(out_dir, f"{base_name}.csv")

        table_payload = []
        csv_lines = []
        for table in tables:
            rows = table.df.fillna("").astype(str).values.tolist()
            table_payload.append({"rows": rows})
            for row in rows:
                csv_lines.append(",".join(row))
            csv_lines.append("")

        with open(json_out, "w", encoding="utf-8") as handle:
            json.dump(table_payload, handle, indent=2)
        with open(csv_out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(csv_lines).rstrip() + "\n")

        page_json["camelotTablesPath"] = f"camelot_tables/{base_name}.json"
        page_json["camelotTablesCsv"] = f"camelot_tables/{base_name}.csv"
        page_json["camelotTableCount"] = len(tables)

        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(page_json, handle, indent=2)

        report["pagesProcessed"] += 1
        report["tablesFound"] += len(tables)
        report["topPages"].append(
            {
                "globalPageIndex": page_index,
                "gapCount": gap_count,
                "sourcePdf": source_pdf,
                "sourcePageNumber": source_page,
                "camelotTableCount": len(tables),
            }
        )

    report_path = os.path.join(output_root, "gap_table_pass12.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print("Gap table pass complete.")


if __name__ == "__main__":
    main()
