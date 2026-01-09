import json
import os
import subprocess


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    validation_path = os.path.join(output_root, "validation_pass4.json")
    raster_dir = os.path.join(output_root, "raster_poppler")
    os.makedirs(raster_dir, exist_ok=True)

    poppler_bin = os.path.join(
        repo_root,
        "tools",
        "poppler",
        "poppler-25.12.0",
        "Library",
        "bin",
        "pdftoppm.exe",
    )

    if not os.path.exists(poppler_bin):
        raise FileNotFoundError(f"pdftoppm not found: {poppler_bin}")

    with open(validation_path, "r", encoding="utf-8") as handle:
        validation = json.load(handle)

    pdf_paths = {os.path.basename(p): p for p in validation.get("sourcePdfs", [])}
    if not pdf_paths:
        manifest_path = os.path.join(output_root, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        pdf_paths = {os.path.basename(p): p for p in manifest.get("sourcePdfs", [])}

    for page in validation.get("pages", []):
        if not page.get("lowConfidence"):
            continue

        source_pdf = page.get("sourcePdf")
        page_num = page.get("sourcePageNumber")
        pdf_path = pdf_paths.get(source_pdf)
        if not pdf_path or not page_num:
            continue

        base_name = f"page-{page.get('globalPageIndex', 0):04d}"
        out_prefix = os.path.join(raster_dir, base_name)
        out_png = out_prefix + "-1.png"
        if os.path.exists(out_png):
            continue

        args = [
            poppler_bin,
            "-r",
            "200",
            "-f",
            str(page_num),
            "-l",
            str(page_num),
            "-png",
            pdf_path,
            out_prefix,
        ]
        subprocess.run(args, check=True)

    print("Poppler raster pass complete.")


if __name__ == "__main__":
    main()
