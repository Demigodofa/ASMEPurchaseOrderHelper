import re


SPEC_RE = re.compile(r"\b(?P<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", re.IGNORECASE)
ITEM_RE = re.compile(r"^\s*\d{1,3}(\.\d+)*[.)]\s+")
SECTION_HEADER_RE = re.compile(r"^\s*\d{1,3}(\.\d+)*\s+[A-Z][A-Za-z].*")

_TRANSLATE_TABLE = {
    ord("\u2018"): "'",
    ord("\u2019"): "'",
    ord("\u201c"): '"',
    ord("\u201d"): '"',
    ord("\u2013"): "-",
    ord("\u2014"): "-",
    ord("\u00b7"): " ",
    ord("\u00b0"): " deg",
    ord("\u00b2"): "2",
    ord("\u00b3"): "3",
    ord("\ufb01"): "fi",
    ord("\ufb02"): "fl",
}

_UNIT_RE = re.compile(
    r"\b(?:in\.?|inch(?:es)?|ft|feet|mm|cm|m|micron|psi|ksi|mpa|kpa|pa|bar|"
    r"lb|lbs|pound(?:s)?|kg|g|oz|deg(?:ree)?s?\s*[cf]|deg[cf]|"
    r"n/mm2|n/mm\^2|n/mm2|%|\u00b0[cf])\b",
    re.IGNORECASE,
)
_MODAL_RE = re.compile(r"\b(shall|should|may|must|will)\b", re.IGNORECASE)


def detect_spec_header(text: str) -> str | None:
    if not text:
        return None
    lines = text.replace("\r\n", "\n").split("\n")[:10]
    for line in lines:
        line_norm = re.sub(r"\s+", " ", line.strip())
        if not line_norm:
            continue
        if "TABLE" in line_norm.upper():
            continue
        match = SPEC_RE.search(line_norm)
        if not match:
            continue
        spec = match.group("spec").upper()
        if line_norm.startswith(spec) or "SPECIFICATION" in line_norm.upper() or "ASME" in line_norm.upper():
            return spec
    header_block = " ".join(lines)
    match = SPEC_RE.search(header_block)
    return match.group("spec").upper() if match else None


def _is_table_row(line: str) -> bool:
    if "|" in line:
        return line.count("|") >= 2
    if not re.search(r"\S\s{2,}\S", line):
        return False
    cols = [part for part in re.split(r"\s{2,}", line.strip()) if part]
    return len(cols) >= 3


def _is_section_header(line: str) -> bool:
    if not ITEM_RE.match(line):
        return False
    title = ITEM_RE.sub("", line).strip()
    if not title:
        return False
    words = [word for word in title.split() if word]
    if len(words) > 6 or len(title) > 60:
        return False
    return all(word[0].isupper() for word in words if word[0].isalpha())


def _is_heading_line(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    if SPEC_RE.search(line) and ("SPECIFICATION" in line.upper() or "ASME" in line.upper()):
        return True
    if SECTION_HEADER_RE.match(line) and _is_section_header(line):
        return True
    letters = [ch for ch in line if ch.isalpha()]
    if len(letters) < 4:
        return False
    uppercase = sum(1 for ch in letters if ch.isupper())
    return (uppercase / len(letters)) >= 0.7 and len(line) <= 80


def chunk_text(text: str) -> list[dict]:
    lines = text.replace("\r\n", "\n").split("\n")
    chunks = []
    current = []
    current_type = None

    def flush():
        nonlocal current, current_type
        if current:
            chunks.append({"type": current_type or "paragraph", "text": "\n".join(current).strip()})
            current = []
            current_type = None

    for line in lines:
        if not line.strip():
            flush()
            continue
        if _is_heading_line(line):
            flush()
            chunks.append({"type": "heading", "text": line.strip()})
            continue
        if _is_table_row(line):
            flush()
            chunks.append({"type": "table", "text": line.rstrip()})
            continue
        if ITEM_RE.match(line) and not _is_section_header(line):
            flush()
            current = [line.rstrip()]
            current_type = "item"
            continue
        if current_type == "item":
            current.append(line.rstrip())
        else:
            if current_type is None:
                current_type = "paragraph"
            current.append(line.rstrip())

    flush()
    return chunks


def segment_text_with_separators(text: str) -> dict:
    lines = text.splitlines(keepends=True)
    segments = []
    current = []
    current_type = None
    pending_sep = ""
    leading_sep = ""

    def flush():
        nonlocal current, current_type, pending_sep
        if current:
            segments.append(
                {
                    "type": current_type or "paragraph",
                    "text": "".join(current),
                    "sep": pending_sep,
                }
            )
            current = []
            current_type = None
            pending_sep = ""

    for line in lines:
        if not line.strip():
            if current:
                pending_sep += line
            else:
                leading_sep += line
            continue

        is_heading = _is_heading_line(line)
        is_table = _is_table_row(line)
        is_item = ITEM_RE.match(line) and not _is_section_header(line)

        if is_heading or is_table or is_item:
            if current:
                flush()
            current = [line]
            if is_heading:
                current_type = "heading"
            elif is_table:
                current_type = "table"
            else:
                current_type = "item"
            continue

        if current_type == "item":
            current.append(line)
        else:
            if current and current_type in {"heading", "table"}:
                flush()
                current = [line]
                current_type = "paragraph"
            else:
                if not current:
                    current_type = "paragraph"
                current.append(line)

    flush()
    return {"leading": leading_sep, "segments": segments}


def normalize_for_compare(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\n", " ")
    text = text.translate(_TRANSLATE_TABLE)
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_numbers(text: str) -> list[str]:
    if not text:
        return []
    text = text.replace(",", "")
    return re.findall(r"\d+(?:\.\d+)?", text)


def extract_units(text: str) -> list[str]:
    if not text:
        return []
    matches = []
    for raw in _UNIT_RE.findall(text.lower()):
        token = raw.lower()
        token = token.replace("degrees", "deg").replace("degree", "deg")
        token = token.replace(" ", "")
        token = token.replace(".", "")
        token = token.replace("\u00b0", "deg")
        token = token.replace("lbs", "lb").replace("pounds", "lb")
        token = token.replace("n/mm^2", "n/mm2").replace("n/mm\u00b2", "n/mm2")
        matches.append(token)
    return matches


def extract_modals(text: str) -> list[str]:
    if not text:
        return []
    return [match.lower() for match in _MODAL_RE.findall(text)]


def is_safe_variant(base_text: str, candidate_text: str) -> bool:
    if not base_text or not candidate_text:
        return False
    if normalize_for_compare(base_text) != normalize_for_compare(candidate_text):
        return False
    if extract_numbers(base_text) != extract_numbers(candidate_text):
        return False
    if extract_units(base_text) != extract_units(candidate_text):
        return False
    if extract_modals(base_text) != extract_modals(candidate_text):
        return False
    return True
