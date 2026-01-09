# ASMEPurchaseOrderHelper

PC UI tool to help purchasing agents generate correct ASME purchase orders. The app will extract ASME material requirements from OCR-processed PDFs and store structured metadata locally for fast lookup and form auto-population.

## Source of truth (for agents/bots)
This README is the source of truth for rules, orientation, and guidance. The owner may use loose or exact language; if there is any ambiguity, confirm intent. Example: if they say "ordering requirements," confirm they mean "Ordering Information" (the official section name used in the PDFs).

## Digitization plan (full document, in progress)
- Goal: fully digitize Section II Part A PDFs once, then iterate on the digitized corpus instead of re-reading the PDFs each time.
- Output location: `sectionII_partA_data_digitized/` in the repo root.
- Outputs:
  - Machine-friendly: per-page JSON with text blocks and confidence signals; separate tables JSON with cell grid data.
  - Human-friendly: per-page plain text and a tables export (format TBD, likely Markdown or TSV).
- Strategy:
  - Pass 1: fast text extraction (PdfPig) with spacing normalization and page metadata.
  - Pass 2: OCR only for low-confidence pages/regions.
  - Pass 3: table extraction on detected table pages, including note linkage.
  - Pass 13: confidence uplift via cross-reference and consistency checks to infer likely gaps.
  - Pass 14: confidence recheck against OCR text; only accept matches at >=95% confidence with anchors.
  - Pass 15: note-targeted OCR around NOTE callouts (no inference, OCR-only).
  - Pass 16: table-targeted OCR around TABLE callouts to verify headers and notes.
  - Pass 17: spec boundary recheck using OCR on top-of-page headers for intrusion pages.
  - Pass 18: full-page 600 DPI OCR for gap/low-confidence pages (batched).
  - Pass 19: export per-spec corpus for downstream AI review (no inference).
  - Pass 20: merge AI-verified notes into spec corpus (resolved notes section).
  - Pass 21: targeted OCR for missing_no_candidate items; merge found notes/tables.
- Merge: produce a single "best available" corpus for querying and validation.
- Notes: tool choice is flexible; prefer accuracy and repeatability over speed.

## Digitization tooling (installed)
- Python libraries: `pypdf`, `pdfplumber`, `pdfminer.six`, `PyMuPDF`, `camelot-py`, `tabula-py`, `ocrmypdf`, `pytesseract`.
- System tools: `tesseract` (OCR) and `java` (Tabula) are installed via Chocolatey.
- Optional accelerator: `jpype1` is installed to let Tabula run in-process.
- Known warning: Tabula/PDFBox may log `jbig2-imageio` missing; this affects JBIG2 images only and can be addressed later if needed.
- Poppler binaries: installed under `tools/poppler/poppler-25.12.0/Library/bin` (use `pdftoppm.exe` for high-fidelity rasterization).
- Installer: `scripts/install_poppler.ps1` downloads Poppler binaries into `tools/poppler/`.

## Digitization runbook (pass 1)
- Script (primary): `scripts/digitize_sectionII_partA.py`
- Script (optional): `scripts/Digitize-SectionII-PartA.ps1` (requires PowerShell 7+ and .NET 8 runtime; Windows PowerShell 5.x cannot load PdfPig).
- Inputs: uses `PoApp.Ingest.Cli/appsettings.json` (`Paths:PdfFiles` preferred; falls back to `Paths:PdfSourceRoot`).
- Dependencies:
  - Python: `pypdf` (installed locally).
  - PowerShell: PdfPig from `PoApp.Ingest.Cli/bin/Debug/net8.0`.
- Outputs:
  - `sectionII_partA_data_digitized/manifest.json`
  - `sectionII_partA_data_digitized/pages/page-0001.json` (per page)
  - `sectionII_partA_data_digitized/pages/page-0001.txt` (per page)
  - `sectionII_partA_data_digitized/tables/page-0001.md` (per page)
  - `sectionII_partA_data_digitized/tables/page-0001.tsv` (per page)
- Table heuristic (pass 1): split lines on 2+ spaces; 3+ columns = table row; consecutive rows form a table.
- Notes capture (pass 1): any line starting with `NOTE`, `NOTES`, or `Note` is appended under "Notes" in the per-page table Markdown.
- Limitations (pass 1): word bounding boxes and table cell geometry are not captured; these will be added in later passes.
- Git hygiene: keep digitized outputs committed as part of the repo state; do not delete PDFs or include copyrighted PDF content.

## Digitization runbook (pass 2 - OCR)
- Script: `scripts/ocr_pass2.py`
- OCR heuristic: `text length < 300` or `alpha ratio < 0.2` triggers OCR.
- Outputs:
  - `sectionII_partA_data_digitized/ocr/page-0001.txt`
  - `sectionII_partA_data_digitized/ocr_pass2_log.json`
- Page JSON updates: `ocrApplied`, `ocrTextPath`, `ocrTextLength`.

## Digitization runbook (pass 3 - tables, Tabula)
- Script: `scripts/table_pass3.py`
- Trigger: pages likely containing tables (keyword "Table" or repeated multi-space columns).
- Outputs:
  - `sectionII_partA_data_digitized/tables_tabula/page-0001.json`
  - `sectionII_partA_data_digitized/tables_tabula/page-0001.csv`
  - `sectionII_partA_data_digitized/table_pass3_log.json`
- Page JSON updates: `tabulaTablesPath`, `tabulaTablesCsv`, `tabulaTableCount`.
- Notes: Tabula uses `pdfbox.fontcache` set under `sectionII_partA_data_digitized/pdfbox-fontcache/` to avoid permission warnings.

## Digitization runbook (pass 4 - validation + raster fallback)
- Script: `scripts/validate_pass4.py`
- Trigger: runs over all pages to score confidence and flag gaps.
- Outputs:
  - `sectionII_partA_data_digitized/validation_pass4.json`
  - `sectionII_partA_data_digitized/raster_low_conf/page-0001.png` (only for low-confidence pages)
- Heuristics:
  - Low confidence: `text length < 300` or `alpha ratio < 0.2`.
  - Table gap: "Table" mention but no `tabulaTablesPath`.
  - Note gap: "Note" mention but `noteCount == 0`.

## Digitization runbook (pass 5 - Poppler raster)
- Script: `scripts/raster_poppler_pass5.py`
- Trigger: low-confidence pages from `validation_pass4.json`.
- Outputs:
  - `sectionII_partA_data_digitized/raster_poppler/page-0001-1.png`
- Notes: uses Poppler `pdftoppm` for more accurate page images than PyMuPDF.

## Digitization runbook (pass 6 - merge best text)
- Script: `scripts/merge_pass6.py`
- Trigger: combines pass 1 text with OCR text where it improves confidence.
- Outputs:
  - `sectionII_partA_data_digitized/best_text/pages/page-0001.txt`
  - `sectionII_partA_data_digitized/best_text/combined.txt`
  - `sectionII_partA_data_digitized/merge_pass6.json`
- Page JSON updates: `bestTextPath`, `bestTextSource`, `bestTextLength`, `bestTextAlphaRatio`.

## Digitization runbook (pass 7 - note gap OCR)
- Script: `scripts/note_gap_pass7.py`
- Trigger: pages flagged with `noteGap` in `validation_pass4.json`.
- Outputs:
  - `sectionII_partA_data_digitized/note_ocr/page-0001.txt`
  - `sectionII_partA_data_digitized/note_gap_pass7.json`
- Page JSON updates: `noteOcrPath`, `noteOcrCount`, `noteOcrNotes`.

## Digitization runbook (pass 7b - high-DPI note gap OCR)
- Script: `scripts/note_gap_pass7b.py`
- Trigger: pages with `noteGap` and zero notes after pass 7.
- Outputs:
  - `sectionII_partA_data_digitized/note_ocr_highdpi/page-0001.txt`
  - `sectionII_partA_data_digitized/note_gap_pass7b.json`
- Page JSON updates: `noteOcrHighDpiPath`, `noteOcrHighDpiCount`, `noteOcrHighDpiNotes`.

## Digitization runbook (pass 8 - TOC cross-check)
- Script: `scripts/toc_pass8.py`
- Trigger: scans pages containing "TABLE OF CONTENTS" and compares spec entries to header matches.
- Outputs:
  - `sectionII_partA_data_digitized/toc_pass8.json`
- Notes: TOC page numbers are recorded as-is; header matches rely on top-of-page spec detection.

## Digitization runbook (pass 8b - TOC cross-check, best-text)
- Script: `scripts/toc_pass8b.py`
- Trigger: scans "TABLE OF CONTENTS"/"CONTENTS" pages using best-text output.
- Outputs:
  - `sectionII_partA_data_digitized/toc_pass8b.json`
- Notes: de-duplicates by spec+page number and records the source TOC line.

## Digitization runbook (pass 8c - TOC OCR, Poppler + Tesseract)
- Script: `scripts/toc_pass8c.py`
- Trigger: OCR on TOC pages (page 3-15 of the first PDF) using Poppler raster and Tesseract layout data.
- Outputs:
  - `sectionII_partA_data_digitized/toc_pass8c.json`
  - `sectionII_partA_data_digitized/toc_raster/` (TOC page images)

## Digitization runbook (pass 10 - TOC index)
- Script: `scripts/toc_index_pass10.py`
- Trigger: uses `toc_pass8c.json` to build a TOC-based spec index and range starts.
- Outputs:
  - `sectionII_partA_data_digitized/toc_index_pass10.json`

## Digitization runbook (pass 10c - TOC order check)
- Script: `scripts/toc_order_pass10c.py`
- Trigger: checks TOC index ordering for start-page regressions.
- Outputs:
  - `sectionII_partA_data_digitized/toc_order_pass10c.json`

## Digitization runbook (pass 10b - gap re-OCR, top 20 pages)
- Script: `scripts/gap_reocr_pass10b.py`
- Trigger: uses `crossref_pass9.json` to find top 20 pages with table/note gaps.
- Outputs:
  - `sectionII_partA_data_digitized/gap_ocr_highdpi/`
  - `sectionII_partA_data_digitized/gap_reocr_pass10b.json`
- Page JSON updates: `gapOcrHighDpiPath`, `gapOcrHighDpiLength`.

## Digitization runbook (pass 9 - cross-reference validation)
- Script: `scripts/crossref_pass9.py`
- Trigger: checks best-text for table/note references and section regressions.
- Outputs:
  - `sectionII_partA_data_digitized/crossref_pass9.json`

## Digitization runbook (pass 12 - targeted table extraction)
- Script: `scripts/gap_table_pass12.py`
- Trigger: uses `crossref_pass9.json` to target top 20 gap pages for Camelot table extraction.
- Outputs:
  - `sectionII_partA_data_digitized/camelot_tables/`
  - `sectionII_partA_data_digitized/gap_table_pass12.json`
- Page JSON updates: `camelotTablesPath`, `camelotTablesCsv`, `camelotTableCount`.

## Digitization runbook (pass 11 - spec range validation)
- Script: `scripts/spec_range_pass11.py`
- Trigger: uses `toc_index_pass10.json` to validate spec ranges and header intrusions.
- Outputs:
  - `sectionII_partA_data_digitized/spec_range_pass11.json`
## Digitization runbook (pass 13 - confidence uplift)
- Script: `scripts/confidence_uplift_pass13.py`
- Trigger: clusters note texts, flags table schema anomalies, and scans section numbering gaps to suggest likely fills.
- Outputs:
  - `sectionII_partA_data_digitized/confidence_uplift_pass13.json`

## Digitization runbook (pass 14 - confidence recheck)
- Script: `scripts/confidence_recheck_pass14.py`
- Trigger: verifies note references and TOC spec starts using OCR text; only marks verified when confidence >= 0.95 and anchors match (note number + spec range).
- Outputs:
  - `sectionII_partA_data_digitized/confidence_recheck_pass14.json`
- Inputs scanned: `best_text`, `ocr`, `note_ocr`, `note_ocr_highdpi`, `note_target_ocr`, `gap_ocr_highdpi`.

## Digitization runbook (pass 15 - note-targeted OCR)
- Script: `scripts/note_target_pass15.py`
- Trigger: OCRs cropped regions around NOTE callouts on pages flagged by `crossref_pass9.json`.
- Outputs:
  - `sectionII_partA_data_digitized/note_target_ocr/`
  - `sectionII_partA_data_digitized/note_target_pass15.json`

## Digitization runbook (pass 16 - table recheck OCR)
- Script: `scripts/table_recheck_pass16.py`
- Trigger: OCRs cropped regions around TABLE callouts on pages flagged by `crossref_pass9.json`.
- Outputs:
  - `sectionII_partA_data_digitized/table_target_ocr/`
  - `sectionII_partA_data_digitized/table_recheck_pass16.json`

## Digitization runbook (pass 17 - spec boundary recheck)
- Script: `scripts/spec_boundary_recheck_pass17.py`
- Trigger: OCR top-of-page headers for spec-range intrusion pages to confirm spec headers and section numbers.
- Outputs:
  - `sectionII_partA_data_digitized/spec_boundary_recheck_pass17.json`

## Digitization runbook (pass 18 - full-page high-DPI OCR)
- Script: `scripts/full_ocr_highdpi_pass18.py`
- Trigger: OCR full pages at 600 DPI for low-confidence pages and table/note gap pages within spec ranges.
- Outputs:
  - `sectionII_partA_data_digitized/full_ocr_highdpi/`
  - `sectionII_partA_data_digitized/full_ocr_highdpi_pass18.json`
- Notes: batched; set `FULL_OCR_MAX_PAGES=0` to run all remaining pages.

## Digitization runbook (pass 18 merge)
- Script: `scripts/merge_pass18.py`
- Trigger: merges `full_ocr_highdpi` into `best_text` when it improves alpha ratio/length.
- Outputs:
  - `sectionII_partA_data_digitized/merge_pass18.json`

## Digitization runbook (pass 19 - spec corpus export)
- Script: `scripts/export_spec_corpus_pass19.py`
- Trigger: exports per-spec corpus (text + page assets) using TOC-derived ranges.
- Outputs:
  - `sectionII_partA_data_digitized/spec_corpus/<SPEC>/spec.json`
  - `sectionII_partA_data_digitized/spec_corpus/<SPEC>/spec.txt`
  - `sectionII_partA_data_digitized/spec_corpus/spec_corpus_index.json`

## Digitization runbook (pass 20 - merge AI-verified notes)
- Script: `scripts/merge_ai_verified_notes_pass20.py`
- Trigger: merges AI note items with confidence >= 0.90 into each `spec.txt` under a "Resolved Notes (AI-verified)" section.
- Outputs:
  - `sectionII_partA_data_digitized/merge_ai_verified_notes_pass20.json`
- Notes: uses existing spec text on the candidate page when possible; otherwise falls back to AI evidence snippet.

## Digitization status
- Pass 1 complete: 1696 pages digitized into `sectionII_partA_data_digitized/`.
- Pass 2 complete: OCR applied to 301 pages (`ocr_pass2_log.json`).
- Pass 3 complete: Tabula tables processed on 910 pages; tables found on 646 pages (`table_pass3_log.json`).
- Pass 4 complete: validation report generated (`validation_pass4.json`).
- Pass 5 complete: Poppler rasters generated for 301 low-confidence pages (`raster_poppler/`).
- Pass 6 complete: best-text merge completed (OCR preferred on 295 pages) (`merge_pass6.json`).
- Pass 7 complete: note-gap OCR processed 80 pages; notes found on 28 pages (`note_gap_pass7.json`).
- Pass 8 complete: TOC cross-check report generated (`toc_pass8.json`).
- Pass 7b complete: high-DPI note-gap OCR processed remaining pages (`note_gap_pass7b.json`).
- Pass 8b complete: best-text TOC report generated (`toc_pass8b.json`).
- Pass 9 complete: cross-reference report generated (`crossref_pass9.json`).
- Pass 8c complete: TOC OCR report generated (`toc_pass8c.json`).
- Pass 10 complete: TOC index generated (`toc_index_pass10.json`).
- Pass 10b complete: gap re-OCR for top 20 pages (`gap_reocr_pass10b.json`).
- Pass 11 complete: spec-range validation report generated (`spec_range_pass11.json`).
- Pass 10c complete: TOC order check report generated (`toc_order_pass10c.json`).
- Pass 12 complete: targeted Camelot tables extracted (`gap_table_pass12.json`).
- Pass 13 complete: confidence uplift report generated (`confidence_uplift_pass13.json`).
  - Summary: note pool 547, clusters 446, table schema flags 153, section gap signals 425.
- Pass 14 complete: confidence recheck report (`confidence_recheck_pass14.json`).
  - Summary: note refs checked 250, verified 0, needs recheck 203, missing 47, TOC starts verified 45/45 (unchanged after pass 15).
- Pass 15 pending: note-targeted OCR pass (`note_target_pass15.json`).
- Pass 15 complete: note-targeted OCR pass (`note_target_pass15.json`).
  - Summary: target pages 118, notes extracted 199.
- Pass 16 complete: table recheck OCR pass (`table_recheck_pass16.json`).
  - Summary: target pages 70, table regions OCR 69.
- Pass 17 complete (batched): spec boundary recheck (`spec_boundary_recheck_pass17.json`).
  - Summary: pages processed 1209/1209, spec header hits 1202, expected matches 134, 1 page missing from manifest (removed duplicate).
- Pass 18 complete: full-page high-DPI OCR (`full_ocr_highdpi_pass18.json`) and merge (`merge_pass18.json`).
  - Summary: pages processed 355/355, remaining 0 (batched at 50 per run).
- Pass 19 pending: spec corpus export (`spec_corpus/`).
- Pass 19 complete: spec corpus export (`spec_corpus/`).
  - Summary: 41 spec corpora created (TOC-range based).
- Pass 20 complete: merge AI-verified notes (`merge_ai_verified_notes_pass20.json`).
  - Summary: specs updated 23, notes merged 122.
  - Threshold updated to 0.90; rerun produced no additional merges (latest AI file has no needs_verification >= 0.90).
## Digitization runbook (pass 21 - target missing candidates)
- Script: `scripts/target_missing_candidates_pass21.py`
- Trigger: OCRs ±3 pages around each missing_no_candidate hit and merges any found note/table into spec.txt under a targeted section.
- Outputs:
  - `sectionII_partA_data_digitized/missing_target_pass21.json`
  - `sectionII_partA_data_digitized/missing_target_ocr/`

## Digitization runbook (pass 21b - full scan missing candidates)
- Script: `scripts/target_missing_candidates_pass21b.py`
- Trigger: OCRs full spec PDFs (or up to `MISSING_FULL_SCAN_MAX_PAGES`) to locate missing note/table definitions.
- Outputs:
  - `sectionII_partA_data_digitized/missing_target_pass21b.json`
  - `sectionII_partA_data_digitized/missing_target_ocr_full/`

## AI review artifacts
- Latest strict AI review outputs live in `sectionII_partA_data_digitized/ai_review/`:
  - `spec_corpus_ai_review.json`
  - `spec_corpus_ai_review.md`
  - `missing_no_candidate_hit_list.md`
  - Note: temporary AI handoff folders and verification packets were cleaned up after merge.

## Conversation log (manual summary)
- You asked to persist the key steps from our work into this README (this section).
- AI-verified notes were merged into spec corpus under "Resolved Notes (AI-verified)" for 23 specs (122 notes).
- Spec ranges corrected for SA-522/SA-134/SA-263/SA-1058 and spec corpus regenerated.
- Targeted OCR (pass 21c) resolved all 10 missing_no_candidate items and merged them.
- Added `scripts/footnote_review_tool.py` to isolate superscripts in footers with a heuristic score.
- Manual note definitions were inserted for remaining gaps; crossref now reports noteRefGaps = 0.
- Validation updated; noteMentionWithoutNotes now 20.
- Normalized OCR artifact "°P" -> "°F" in best_text pages.
- Remaining focus: tableRefGaps = 146 and sectionRegressions = 138.

## Placeholder tracking
- Removed page placeholders are recorded in `sectionII_partA_data_digitized/removed_pages_placeholders.json` to keep global page gaps explicit.

## Reusable scripts/tools (for other PDFs)
- `scripts/digitize_sectionII_partA.py`: fast text extraction + basic table heuristic (seed pass for any PDF set).
- `scripts/ocr_pass2.py`: OCR low‑confidence pages based on text length/alpha ratio.
- `scripts/table_pass3.py`: Tabula table extraction on suspected table pages.
- `scripts/validate_pass4.py`: confidence scoring + gap detection; drives raster/targeted passes.
- `scripts/raster_poppler_pass5.py`: Poppler high‑fidelity raster for low‑confidence pages.
- `scripts/merge_pass6.py`: best‑text merge from OCR + text extraction.
- `scripts/note_gap_pass7.py` / `note_gap_pass7b.py`: OCR note‑gap pages (standard + high DPI).
- `scripts/toc_pass8.py` / `toc_pass8b.py` / `toc_pass8c.py`: TOC extraction (best‑text + OCR).
- `scripts/toc_index_pass10.py` / `toc_order_pass10c.py`: TOC indexing + ordering validation.
- `scripts/crossref_pass9.py`: table/note reference gap detection + section regressions.
- `scripts/gap_reocr_pass10b.py`: targeted high‑DPI OCR on top gap pages.
- `scripts/gap_table_pass12.py`: targeted Camelot table extraction on top gap pages.
- `scripts/spec_range_pass11.py`: TOC‑driven spec range validation.
- `scripts/confidence_uplift_pass13.py`: consistency checks to flag gaps (no auto‑fill).
- `scripts/confidence_recheck_pass14.py`: anchored verification pass (>=95% confidence).
- `scripts/note_target_pass15.py`: OCR cropped note callouts on reference pages.
- `scripts/table_recheck_pass16.py`: OCR cropped table callouts on reference pages.
- `scripts/spec_boundary_recheck_pass17.py`: OCR top‑of‑page headers for spec boundary verification (batched).
- `scripts/install_poppler.ps1`: installs Poppler `pdftoppm` for raster passes.
- `scripts/footnote_review_tool.py`: generates footer crops + OCR TSV and a scored report to confirm superscripts/footnotes.
- Directions: set `PoApp.Ingest.Cli/appsettings.json` `Paths:PdfFiles` or `Paths:PdfSourceRoot`, then run passes in order and re‑run pass 4/9 to update confidence metrics.

## Goals
- Ensure purchase orders include all ASME-required values for each material.
- Build a growing, reusable knowledge base of ASME material data.
- Provide a fast, friendly UI with search, auto-population, and controlled inputs.

## Data sources
- OCR-processed ASME PDFs (over 1,000 pages).
- Target fields (initial): Material spec, material grades, ASTM grade, accepted year.
- More fields to be added as coverage expands.

Current PDF paths used by the ingest CLI:
- `C:\Users\KevinPenfield\Desktop\2025 OCR SECT II PART A BEGINNING TO SA-450.pdf`
- `C:\Users\KevinPenfield\Desktop\2025 OCR ASME SECT II MATERIALS PART A SA-451 TO END.pdf`
- Part B (nonferrous) will be added later.

## Key challenges
- Reliable extraction from scattered PDF content (layered/iterative approach).
- Local storage that stays fast and responsive as data grows.

## Planned UI
- WPF desktop interface (single-pane, already roughed out).
- Windows 10/11 only.
- Mix of search, auto-populate, and dropdowns (to be finalized after data ingestion).
- Current UI wiring:
  - Spec selection and Spec Type (blank/SA/A).
  - ASTM equivalent display.
  - Ordering Requirements checklist (from extracted Ordering Information text).
  - Required Fields section (Quantity, Length, Size/OD/Thickness, End Finish) with prompts.
  - PO text preview that includes required fields and ordering requirements.

## Suggested approach
- Parsing: staged extraction (start with a minimal set of fields, expand coverage).
- Storage: structured local database for fast lookups (likely SQLite).
- Validation: enforce required ASME PO fields per material.
- Data location: store the user data file in `%LocalAppData%\ASMEPurchaseOrderHelper\` for write access and easy updates.
- Updates: ship a new EXE + bundled data; on run, migrate/replace the local data file if newer.
- Data layout (to keep it fast and non-brittle):
  - `Materials` table: `SpecDesignation`, `SpecPrefix`, `SpecNumber`, `AstmSpec`, `AstmYear`, `AstmNote`, `Category`, and other core fields.
  - `MaterialGrades` table: `SpecDesignation`, `Grade`.
  - `MaterialNotes` table: `SpecDesignation`, `Note`.
  - This keeps the data normalized, avoids duplication, and scales well as fields grow.

## Configuration
- `PoApp.Desktop/appsettings.json` -> `Paths:PdfSourceRoot` for the local OCR PDF folder.
- `PoApp.Ingest.Cli/appsettings.json` -> `Paths:PdfSourceRoot` for ingestion runs.
- If left blank, the app defaults to the current user's Desktop folder.
- Optional: `Paths:PdfFiles` to list specific PDF file paths (overrides folder scan).
- Optional: `Ingest:ExpectedSpecs` to report missing specs after ingest.
- Optional: `Ingest:ScanMissingSpecs` to scan PDFs for any mentions of missing specs (diagnostic mode).

## Ingest output
- Combined dataset: `data/materials.json`
- Category datasets (for UI buttons): `data/materials-ferrous.json`, `data/materials-nonferrous.json`, `data/materials-electrode.json`
- Ordering Information exports:
  - `data/ordering-items-by-spec.csv`
  - `data/ordering-items-by-spec.json`
- Required field mapping:
  - `data/ordering-required-fields.json`
  - `data/ordering-required-fields.csv`
- End finish mapping:
  - `data/end-finish-normalized.json`
  - `data/ordering-end-finish-items.json`
- Progress tracker:
  - `data/ordering-requirements-status.json`

## Open questions
- Do we want a formal data schema now, or evolve it as we ingest?
- What is the minimum set of fields needed for a first usable version?

## Parsing notes (current behavior)
- Ordering Information is extracted from each material section using the "Ordering Information" heading and its numbered sub-items.
- Table of Contents extraction is used to avoid false spec headers and to improve detection.
- End finish rules:
  - Any Ordering Information referencing `A999/A999M` is treated as "Plain ends unless specified."
  - Any Ordering Information stating "plain or threaded" yields dropdown options.
  - Other spec-specific end finish rules are captured verbatim in `data/end-finish-normalized.json`.

## Parsing notes (current ingest truths)
- Ordering Information detection uses a section header like `3. Ordering Information` (any section number).
- The extraction boundary ends at the next top-level section header (e.g., `4. Scope`), based on a numeric header plus capitalized title.
- Ordering Information items are only captured when they start with the same section number prefix (e.g., `3.1`, `3.1.1`).
- The ingest concatenates all pages for a spec before extracting Ordering Information items.
- TOC extraction is used only to filter valid spec headers; page ranges are not used yet.

## UI data flow (current behavior)
- Selecting a spec populates:
  - Ordering requirements list (from `OrderingInfoItems`).
  - Required fields (Quantity, Length, Size/OD/Thickness, End Finish) based on `data/ordering-required-fields.json`.
  - End finish notes or options based on `data/end-finish-normalized.json`.
- PO output includes:
  - Material designation (SA/A).
  - ASTM equivalence note/year logic.
  - Selected ordering requirements.
  - Required fields with prompts or provided values.

## Agent autonomy (standing instruction)
- The agent may run commands, edit files, refactor code, commit, and push without asking.
- Ask before changing target framework, UI tech, database choice, adding cloud services, or changing parsing strategy materially.
- Do not commit build artifacts or copyrighted PDF content.

## Next steps
- Use TOC page ranges to capture missing Ordering Information for specs that still have none.
- Expand required-field mapping to additional common requirements (grade, type, welded/seamless, test reports, etc.).
- Wire required-field prompts to the final UI layout and PO output formatting.
- Review pass 13 flags to prioritize targeted OCR/table passes (note gaps likely need tighter matching).
- Run pass 14 to recheck OCR text and only accept >=95% anchored matches.

## Materials coverage (current progress)
- Specs total: 183
- Ordering Information captured: 112 specs
- Ordering Information missing: 71 specs
- Required-field map entries: 183 specs
- Ordering requirement status coverage (true counts):
  - Quantity: 31
  - Length: 24
  - Size/OD/Thickness: 12
  - End Finish Required: 20
  - End Finish Rule Mapped: 20
- Sample missing Ordering Information specs:
  - SA-1010, SA-1017, SA-1017M, SA-1058, SA-181, SA-192, SA-193, SA-203, SA-204, SA-209, SA-225, SA-240, SA-250, SA-283, SA-285, SA-29, SA-299, SA-302, SA-353, SA-36, SA-370, SA-387, SA-387M, SA-4, SA-403

## Quality & testing plan (to implement next)
- Static analysis:
  - Enable .NET analyzers (`<AnalysisLevel>latest</AnalysisLevel>`).
  - Turn on `TreatWarningsAsErrors` once the warnings are under control.
- Unit tests (xUnit):
  - Target parsing and mapping logic first (Ordering Information extraction, end-finish normalization, required-field tagging).
- Integration tests:
  - Ingest CLI end-to-end against a known PDF set; verify output shape and counts.
- UI automation & stress testing:
  - Use **FlaUI** (preferred over WinAppDriver because it is pure .NET, actively maintained, and does not require a separate Windows driver install).
  - Add a UI test harness that rapidly changes selections, fills fields, clears values, and copies output to simulate heavy user interaction.
