import argparse
import json
import os
from pathlib import Path


def parse_tsv_boxes(tsv_path: Path, threshold: float) -> list[dict]:
    boxes = []
    with tsv_path.open("r", encoding="utf-8", errors="ignore") as handle:
        header = True
        for line in handle:
            if header:
                header = False
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 12:
                continue
            level = parts[0]
            if level != "5":
                continue
            text = parts[11]
            if not text:
                continue
            try:
                conf = float(parts[10])
            except ValueError:
                continue
            if conf < 0 or conf >= threshold:
                continue
            left, top, width, height = (int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9]))
            boxes.append(
                {
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "conf": round(conf, 2),
                    "text": text,
                }
            )
    return boxes


def write_overlay_html(output_path: Path, image_rel: str, boxes: list[dict]) -> None:
    box_divs = []
    for box in boxes:
        style = (
            f"left:{box['left']}px;top:{box['top']}px;"
            f"width:{box['width']}px;height:{box['height']}px;"
        )
        title = f"{box['conf']}:{box['text']}".replace('"', "")
        box_divs.append(f"<div class=\"box\" style=\"{style}\" title=\"{title}\"></div>")
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>QA Overlay</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    .canvas {{ position: relative; display: inline-block; }}
    .canvas img {{ display: block; }}
    .box {{
      position: absolute;
      border: 2px solid rgba(255, 0, 0, 0.7);
      background: rgba(255, 0, 0, 0.08);
      box-sizing: border-box;
    }}
  </style>
</head>
<body>
  <div class="canvas">
    <img src="{image_rel}" alt="page image" />
    {"".join(box_divs)}
  </div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate visual QA overlays for low-confidence words.")
    parser.add_argument("--source", required=True, help="Source page packet folder.")
    parser.add_argument("--out", required=True, help="Output folder for HTML overlays.")
    parser.add_argument("--threshold", type=float, default=50.0, help="Confidence threshold.")
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    output_dir = Path(args.out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    index_entries = []

    for page_meta in sorted((source_dir / "pages").glob("page-*.json")):
        payload = json.loads(page_meta.read_text(encoding="ascii", errors="ignore"))
        low_conf = payload.get("lowConfidenceCandidate") or (payload.get("lowConfWordCount", 0) > 0)
        if not low_conf:
            continue
        image_rel = payload.get("imagePath")
        tsv_rel = payload.get("ocrTsvPath")
        if not image_rel or not tsv_rel:
            continue
        image_path = source_dir / image_rel
        tsv_path = source_dir / tsv_rel
        if not image_path.exists() or not tsv_path.exists():
            continue
        boxes = parse_tsv_boxes(tsv_path, args.threshold)
        if not boxes:
            continue
        page_number = payload.get("pageNumber")
        out_page = output_dir / f"page-{page_number:04d}.html"
        image_relative = os.path.relpath(image_path, out_page.parent)
        write_overlay_html(out_page, image_relative, boxes)
        index_entries.append((page_number, out_page.name))

    index_path = output_dir / "index.html"
    links = "\n".join(
        [f"<li><a href=\"{name}\">page-{page:04d}</a></li>" for page, name in index_entries]
    )
    index_html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>QA Overlay Index</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
  </style>
</head>
<body>
  <h1>Low-Confidence Pages</h1>
  <ul>
    {links}
  </ul>
</body>
</html>
"""
    index_path.write_text(index_html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
