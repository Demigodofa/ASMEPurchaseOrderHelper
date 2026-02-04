import argparse
import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path

from PIL import Image
import pytesseract


DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DIGIT_RE = re.compile(r"\d{1,4}")


def configure_tesseract():
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd and Path(cmd).exists():
        pytesseract.pytesseract.tesseract_cmd = cmd
        return
    if Path(DEFAULT_TESSERACT).exists():
        pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def extract_footer_image(
    image: Image.Image, height_ratio: float, center_width_ratio: float
) -> Image.Image:
    width, height = image.size
    y0 = int(height * (1 - height_ratio))
    x0 = 0
    x1 = width
    if center_width_ratio < 1.0:
        crop_w = int(width * center_width_ratio)
        x0 = max(0, int((width - crop_w) / 2))
        x1 = min(width, x0 + crop_w)
    return image.crop((x0, y0, x1, height))


def ocr_footer_number(
    image: Image.Image, psm: int, center_band_ratio: float, max_value: int
) -> tuple[int | None, str, float | None]:
    config = f"--psm {psm} -c tessedit_char_whitelist=0123456789"
    text = pytesseract.image_to_string(image, config=config)
    data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)

    best = None
    mid_x = image.width / 2
    band_half = (image.width * center_band_ratio) / 2
    for idx, word in enumerate(data.get("text", [])):
        token = word.strip()
        if not token.isdigit() or len(token) > 4:
            continue
        value = int(token)
        if value < 1 or value > max_value:
            continue
        left = data["left"][idx]
        width = data["width"][idx]
        center_x = left + (width / 2)
        if abs(center_x - mid_x) > band_half:
            continue
        y = data["top"][idx]
        h = data["height"][idx]
        conf = data["conf"][idx]
        try:
            conf_val = float(conf) if conf != "-1" else None
        except ValueError:
            conf_val = None
        if best is None or (y + h) > (best["y"] + best["h"]):
            best = {"num": value, "y": y, "h": h, "conf": conf_val}

    if best:
        return best["num"], text.strip(), best["conf"]

    digits = DIGIT_RE.findall(text or "")
    if not digits:
        return None, text.strip(), None
    return int(digits[-1]), text.strip(), None


def resolve_text_path(source_root: Path, page_json: dict) -> Path | None:
    path = page_json.get("pdfTextPath") or page_json.get("ocrTextPath")
    if not path:
        return None
    candidate = source_root / path
    return candidate if candidate.exists() else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR footer numbers and emit footer-labeled page text files."
    )
    parser.add_argument("--source-root", required=True, help="Packet source root (has pages/, images/).")
    parser.add_argument("--out", required=True, help="Output folder for footer labels.")
    parser.add_argument("--label", required=True, help="Source label for reporting.")
    parser.add_argument("--height-ratio", type=float, default=0.2, help="Footer crop height ratio.")
    parser.add_argument(
        "--center-width-ratio",
        type=float,
        default=1.0,
        help="Footer crop width ratio centered on page.",
    )
    parser.add_argument("--psm", type=int, default=7, help="Tesseract page segmentation mode.")
    parser.add_argument(
        "--center-band-ratio",
        type=float,
        default=0.5,
        help="Keep digits within this centered band ratio of the crop width.",
    )
    parser.add_argument(
        "--max-footer",
        type=int,
        default=5000,
        help="Maximum footer number to accept.",
    )
    parser.add_argument("--max-pages", type=int, default=0, help="Optional max pages to process.")
    args = parser.parse_args()

    configure_tesseract()
    source_root = Path(args.source_root).resolve()
    pages_dir = source_root / "pages"
    images_dir = source_root / "images"
    out_root = Path(args.out).resolve()
    out_pages = out_root / "pages"
    out_pages.mkdir(parents=True, exist_ok=True)

    entries = []
    page_files = sorted(pages_dir.glob("page-*.json"))
    if args.max_pages and args.max_pages > 0:
        page_files = page_files[: args.max_pages]

    for page_json_path in page_files:
        page_data = load_json(page_json_path)
        page_num = page_data.get("pageNumber")
        if not isinstance(page_num, int):
            continue
        image_path = images_dir / f"page-{page_num:04d}.png"
        if not image_path.exists():
            continue
        image = Image.open(image_path)
        footer_img = extract_footer_image(image, args.height_ratio, args.center_width_ratio)
        footer_number, footer_text, footer_conf = ocr_footer_number(
            footer_img, args.psm, args.center_band_ratio, args.max_footer
        )

        text_path = resolve_text_path(source_root, page_data)
        text_content = text_path.read_text(encoding="utf-8", errors="ignore") if text_path else ""

        if footer_number is None:
            labeled_name = f"footer-unknown_page-{page_num:04d}.txt"
        else:
            labeled_name = f"footer-{footer_number:04d}_page-{page_num:04d}.txt"

        (out_pages / labeled_name).write_text(text_content, encoding="utf-8")

        entries.append(
            {
                "pageNumber": page_num,
                "footerNumber": footer_number,
                "footerText": footer_text,
                "footerConf": footer_conf,
                "imagePath": str(image_path),
                "textPath": str(text_path) if text_path else None,
                "labeledTextPath": str(out_pages / labeled_name),
            }
        )

    report = {
        "createdAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "label": args.label,
        "sourceRoot": str(source_root),
        "count": len(entries),
        "entries": entries,
    }
    (out_root / "footer_map.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    with (out_root / "footer_map.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "pageNumber",
                "footerNumber",
                "footerConf",
                "footerText",
                "imagePath",
                "textPath",
                "labeledTextPath",
            ]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.get("pageNumber"),
                    entry.get("footerNumber"),
                    entry.get("footerConf"),
                    entry.get("footerText"),
                    entry.get("imagePath"),
                    entry.get("textPath"),
                    entry.get("labeledTextPath"),
                ]
            )

    print(f"Footer OCR complete: {len(entries)} pages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
