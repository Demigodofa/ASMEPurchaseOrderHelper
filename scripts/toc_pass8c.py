import json
import os
import re
import subprocess
from datetime import datetime, timezone
from PIL import Image
import pytesseract


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def ensure_tesseract():
    if os.path.exists(TESSERACT_EXE):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE


def render_poppler(pdftoppm, pdf_path, first_page, last_page, out_prefix, dpi=300):
    args = [
        pdftoppm,
        "-r",
        str(dpi),
        "-f",
        str(first_page),
        "-l",
        str(last_page),
        "-png",
        pdf_path,
        out_prefix,
    ]
    subprocess.run(args, check=True)


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    output_root = os.path.join(repo_root, "sectionII_partA_data_digitized")
    manifest_path = os.path.join(output_root, "manifest.json")
    toc_dir = os.path.join(output_root, "toc_raster")
    os.makedirs(toc_dir, exist_ok=True)

    pdftoppm = os.path.join(
        repo_root,
        "tools",
        "poppler",
        "poppler-25.12.0",
        "Library",
        "bin",
        "pdftoppm.exe",
    )
    if not os.path.exists(pdftoppm):
        raise FileNotFoundError(f"pdftoppm not found: {pdftoppm}")

    ensure_tesseract()

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    first_pdf = manifest.get("sourcePdfs", [None])[0]
    if not first_pdf:
        raise FileNotFoundError("No source PDFs in manifest.")

    # TOC pages per guidance: page 3-15 in first PDF
    out_prefix = os.path.join(toc_dir, "toc")
    render_poppler(pdftoppm, first_pdf, 3, 15, out_prefix, dpi=200)

    entries = []
    for name in sorted(os.listdir(toc_dir)):
        if not name.startswith("toc-") or not name.endswith(".png"):
            continue
        image_path = os.path.join(toc_dir, name)
        image = Image.open(image_path)
        width, _ = image.size
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config="--psm 6")

        lines = {}
        for i in range(len(data["text"])):
            word = data["text"][i].strip()
            if not word:
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            entry = lines.setdefault(key, [])
            entry.append(
                {
                    "text": word,
                    "left": data["left"][i],
                }
            )

        for words in lines.values():
            words_sorted = sorted(words, key=lambda w: w["left"])
            line_text = " ".join(w["text"] for w in words_sorted)
            spec_match = SPEC_RE.search(line_text)
            if not spec_match:
                continue

            spec_num = int(re.findall(r"\d{1,4}", spec_match.group("spec"))[0])
            # page numbers are typically right-aligned; look for numeric tokens on the right 30%
            right_nums = []
            all_nums = []
            for w in words_sorted:
                if w["text"].isdigit():
                    num = int(w["text"])
                    all_nums.append(num)
                    if w["left"] >= width * 0.7:
                        right_nums.append(num)

            candidates = right_nums if right_nums else all_nums
            candidates = [n for n in candidates if n not in (spec_num, 2025)]
            if not candidates:
                continue

            entries.append(
                {
                    "spec": spec_match.group("spec").upper(),
                    "tocPageNumber": candidates[-1],
                    "tocLine": line_text,
                    "tocImage": os.path.basename(image_path),
                }
            )

    # Dedup
    dedup = {}
    for entry in entries:
        key = (entry["spec"], entry["tocPageNumber"])
        dedup[key] = entry
    entries = list(dedup.values())

    toc_report = {
        "createdUtc": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
        "summary": {
            "tocEntries": len(entries),
        },
    }

    out_path = os.path.join(output_root, "toc_pass8c.json")
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(toc_report, handle, indent=2)

    print("TOC pass 8c complete.")


if __name__ == "__main__":
    main()
