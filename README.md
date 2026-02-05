# ASMEPurchaseOrderHelper

PC UI tool to help purchasing agents generate correct ASME purchase orders. The active desktop flow reads normalized ASME JSONL data, applies policy rules, and generates copy-ready/exportable PO content.

## Source of truth (for agents/bots)
This README is the source of truth for rules, orientation, and guidance. The owner may use loose or exact language; if there is any ambiguity, confirm intent. Example: if they say "ordering requirements," confirm they mean "Ordering Information" (the official section name used in the PDFs).
## Codex Operating Contract (Authoritative)

This README.md is the single source of truth for Codex.

When Codex is running in this repository, it MUST:

- Treat this file as binding instructions
- Never invent file locations, schemas, or rules
- Never delete or overwrite source artifacts unless explicitly instructed
- Only operate within paths documented below
- Ask before changing schemas, directory structure, or parsing strategy

If instructions elsewhere conflict with this README, this README wins.

## Active baseline (2026-02-05)
- Active build inputs for the PO assistant now live in `data/`:
  - `data/asme_po_schema_imperial_v4.json`
  - `data/asme_po_data_imperial_v4.jsonl`
  - `data/CODEX_BUILD_INSTRUCTIONS_ASME_PO_ASSISTANT_IMPERIAL_V4.md`
- Legacy OCR/corpus outputs are archived under `old_data/`:
  - `old_data/data/`
  - `old_data/sectionII_partA_data_digitized/`
- Treat `old_data/` as historical reference. Do not delete unless explicitly requested.

## Additional truth-sourcing workflow (additive)
This is an additional course of action to source the truth; it does not replace or overwrite the current corpus.
- Originals live in `inputs/originals/` (gitignored). Never overwrite or delete originals; keep `inputs/originals_manifest.json` updated with hashes and source tags.
- Corpus merge helpers (additive, no overwrite):
  - `scripts/merge_spec_corpus_complete.py` merges multiple spec corpora into a new output folder (example: `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_complete_v4`).
  - `scripts/merge_spec_corpus.py` merges two corpora (primary wins for shared specs) into a new output folder (example: `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_merged_v1`).
- Stage 0: build per-source page packets (raster + OCR text + word boxes + confidence + page number).
- Stage 0 script: `scripts/build_page_packets_stage0.py`.
- Stage 0 (DOCX) script: `scripts/build_docx_packets_stage0.py`.
- Stage 1: align pages across sources by page number + header/footer anchors + text similarity.
- Stage 1 script: `scripts/align_page_packets_stage1.py`.
- Stage 1b: quilt numbered-item chunks within spec ranges to reduce cross-material drift.
- Stage 1b script: `scripts/quilt_chunks_stage1b.py`.
- Stage 1c: lock consensus chunks (no further swaps/reflow once locked).
- Stage 1c script: `scripts/lock_chunks_stage1c.py`.
- Stage 1d: classify unlocked chunk variants (no text changes).
- Stage 1d script: `scripts/classify_chunk_variants_stage1d.py`.
- Stage 1e: promote auto-resolvable variants into `best_text_promoted` (no reflow).
- Stage 1e script: `scripts/promote_chunks_stage1e.py`.
- Stage 1f: build human-review prioritization queue from review metadata.
- Stage 1f script: `scripts/build_review_queue_stage1f.py`.
- Stage 1g: rebuild review queue with subsection identifiers from classification metadata.
- Stage 1g script: `scripts/build_review_queue_with_subsections_stage1g.py`.
- Stage 1h: build review collapse map for review-once/apply-many groups.
- Stage 1h script: `scripts/build_review_collapse_map_stage1h.py`.
- Stage 1i: report top-N largest review groups from collapse map metadata.
- Stage 1i script: `scripts/build_review_top_groups_stage1i.py`.
- Stage 1j: build human approval intake templates for review groups.
- Stage 1j script: `scripts/build_review_approval_templates_stage1j.py`.
- Stage 1k: preview propagation impact from approval templates (dry-run only).
- Stage 1k script: `scripts/preview_approval_propagation_stage1k.py`.
- Stage 1l: apply approved groups to produce final frozen corpus.
- Stage 1l script: `scripts/apply_approved_groups_stage1l.py`.
- Freeze: `sectionII_partA_data_digitized/rebuild/final_freeze_manifest.json` blocks alignment/swapping/reclassification scripts.
- Versioning: removing the freeze manifest starts a new revision cycle and requires a new version identifier (example v1.0.0 machine-only, v1.1.0 human-amended).
- Freeze manifest should include corpus hashes (Part A + Part B), approval template hash, applied approvals count, and notes.
- Review artifacts are historical evidence: review queues, collapse maps, approval templates, preview reports (treat read-only).
- Comparison report: `scripts/compare_corpus_report.py` compares current spec_corpus text to final best_text outputs.
- Review worksheet: `scripts/build_review_worksheet_stage1m.py` generates a fill-in sheet with chunk text + locations.
- Boundary fix list: `scripts/build_boundary_fix_list_stage1n.py` parses worksheet notes into mapping suggestions.
- Stage 2: layer sources and compute consensus text; track coverage % and provenance.
- Stage 2 script: `scripts/merge_page_packets_stage2.py`.
- Stage 3: visual QA for low-confidence regions via overlays/side-by-side comparison.
- Stage 3 script: `scripts/visual_qa_stage3.py`.
- Stage 4: export `spec_corpus/` and app datasets only after all sources are layered and reviewed.
- Stage 4 scripts: `scripts/build_best_text_stage4.py`, `scripts/export_spec_corpus_stage4.py`.
- Stage 4 helpers: `scripts/build_manifest_stage4.py`, `scripts/build_identity_alignment_stage4.py`, `scripts/spec_range_from_headers_stage4.py`.
- ABBYY DOCX sources are reference-only for QA unless explicitly merged; greyscale DOCX is excluded from consensus merges due to low alignment quality.
- Process Part A first, then bring Part B to the same coverage/QA depth.

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
- Note: `tesseract.exe` may not be on PATH; use `C:\Program Files\Tesseract-OCR\tesseract.exe`.
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

## Digitization runbook (pass 8c - SA-451+ TOC extraction)
- Script: `scripts/toc_pass8c_sa451_end.py`
- Trigger: extract "Specifications Listed by Materials" entries from the SA-451+ PDF.
- Outputs:
  - `sectionII_partA_data_digitized/toc_pass8c_part_a_sa451_end.json`

## Digitization runbook (pass 10 - TOC index)
- Script: `scripts/toc_index_pass10.py`
- Trigger: uses `toc_pass8c.json` to build a TOC-based spec index and range starts.
- Outputs:
  - `sectionII_partA_data_digitized/toc_index_pass10.json`

## Digitization runbook (TOC index - SA-451+)
- Script: `scripts/toc_index_pass10b.py`
- Trigger: build TOC index for the SA-451+ TOC entries.
- Outputs:
  - `sectionII_partA_data_digitized/toc_index_pass10b_sa451_end.json`

## Digitization runbook (pass 10c - TOC order check)
- Script: `scripts/toc_order_pass10c.py`
- Trigger: checks TOC index ordering for start-page regressions.
- Outputs:
  - `sectionII_partA_data_digitized/toc_order_pass10c.json`

## Corpus remediation (page-level overrides)
- Script: `scripts/apply_boundary_fix_overrides.py`
- Trigger: apply footer/TOC overrides to boundary fix list notes.
- Outputs:
  - `sectionII_partA_data_digitized/rebuild/boundary_fix_list_applied.json`
  - `sectionII_partA_data_digitized/rebuild/boundary_fix_list_applied.csv`
- Script: `scripts/export_spec_corpus_with_overrides.py`
- Trigger: export a corrected spec corpus without modifying the original truth corpus.
- Outputs:
  - `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_fixed/`
  - `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_fixed_overrides.json`

## OCR footer alignment (cross-source correlation)
- Script: `scripts/footers_ocr_label_pages.py`
- Trigger: OCR footer page numbers from packet images and emit footer-labeled page text files.
- Outputs (per source):
  - `sectionII_partA_data_digitized/rebuild/footer_ocr_{source}/footer_map.json`
  - `sectionII_partA_data_digitized/rebuild/footer_ocr_{source}/footer_map.csv`
  - `sectionII_partA_data_digitized/rebuild/footer_ocr_{source}/pages/footer-####_page-####.txt`
- Script: `scripts/align_footer_maps.py`
- Trigger: align two footer maps by footer page number.
- Outputs:
  - `footer_alignment_*.json` / `footer_alignment_*.csv`
- Notes: auto-detects a constant footer offset when overlap improves (see `offsetApplied` in report); use `--offset` to force.

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
- Notes: `spec.json` now includes `footerPageNumber` when detected from the page text.

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
- Built an additive merged corpus at `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_complete_v4` from `spec_corpus_part_a_fixed_v3` + `spec_corpus_part_a_quilted` + legacy `spec_corpus` (docx fallback allowed). Current merged count: 60 specs.
- Merged `spec_corpus_part_a_fixed_v3` (primary) with `spec_corpus_part_a_complete_v4` (secondary) into `sectionII_partA_data_digitized/rebuild/spec_corpus_part_a_merged_v1` (primary wins shared specs).
- Promoted `spec_corpus_part_a_merged_v1` to the canonical corpus at `sectionII_partA_data_digitized/spec_corpus`; backup saved as `sectionII_partA_data_digitized/spec_corpus_backup_20260129_135123`.
- Adjusted TOC ranges so SA-135 includes its cover page (SA-106 end set to 236; SA-135 start set to 237); regenerated `spec_range_pass11.json` and re-exported spec corpus.
- Added footer page number extraction to `scripts/export_spec_corpus_pass19.py`, writing `footerPageNumber` into each page entry in `spec.json`.
- Ran ad-hoc OCR sanity checks for SA-36 and SA-135 cover pages using Poppler + Tesseract; outputs live in `sectionII_partA_data_digitized/ocr_checks/`.
- AI-verified notes were merged into spec corpus under "Resolved Notes (AI-verified)" for 23 specs (122 notes).
- Spec ranges corrected for SA-522/SA-134/SA-263/SA-1058 and spec corpus regenerated.
- Targeted OCR (pass 21c) resolved all 10 missing_no_candidate items and merged them.
- Added `scripts/footnote_review_tool.py` to isolate superscripts in footers with a heuristic score.
- Manual note definitions were inserted for remaining gaps; crossref now reports noteRefGaps = 0.
- Validation updated; noteMentionWithoutNotes now 20.
- Normalized OCR artifact "°P" -> "°F" in best_text pages.
- Remaining focus: tableRefGaps = 146 and sectionRegressions = 138.

- Added ABBYY docx ingestion parameterization (pass A0) and truth-merge parameterization (pass A2) to support multiple scans, plus multi-source truth merge (`scripts/truth_merge_abbyy_multi_passA2b.py`).
- Added ABBYY TOC extraction for docx (`scripts/toc_abbyy_docx_pass8d.py`) and TOC vs spec corpus audit with placeholders (`scripts/audit_spec_corpus_toc.py`).
- Created similarity-only ABBYY matcher (`scripts/abbyy_similarity_match.py`) to align docx text to best_text when pages were removed; merged 255 matches into `best_text` (backed up originals).
- Filled 12 placeholder specs from ABBYY greyscale docx (`scripts/fill_placeholders_from_abbyy.py`): SA-6, SA-29, SA-53, SA-178, SA-179, SA-182, SA-192, SA-193, SA-194, SA-209, SA-210, SA-213.
- After ABBYY similarity merge, crossref improved to tableRefGaps 7, noteRefGaps 0, sectionRegressions 99; validation note gaps remain 20 once AI-verified notes are re-merged.
- Part B ABBYY docx (`2025 OCR SECTION II PART B .docx`) ingested; similarity match accepted 9 pages and merged into best_text.
- Re-exported spec corpus from best_text; note that export removes "Resolved Notes (AI-verified)" so rerun `scripts/merge_ai_verified_notes_pass20.py` after export to restore notes before validation.
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
- Primary app build source: normalized JSONL/spec schema in `data/`.
- OCR-processed ASME PDFs and derived corpus outputs are now historical reference in `old_data/`.
- Target fields (initial): Material spec, material grades, ASTM grade, accepted year.
- More fields to be added as coverage expands.

Current PDF paths used by the ingest CLI:
- `C:\Users\KevinPenfield\Desktop\2025 OCR SECT II PART A BEGINNING TO SA-450.pdf`
- `C:\Users\KevinPenfield\Desktop\2025 OCR ASME SECT II MATERIALS PART A SA-451 TO END.pdf`
- Part B (nonferrous) will be added later.

## Key challenges
- Reliable extraction from scattered PDF content (layered/iterative approach).
- Local storage that stays fast and responsive as data grows.

## Current UI (normalized JSONL mode)
- WPF desktop interface (Windows 10/11) now runs directly from normalized JSONL data.
- Top-level context includes:
- Code Use checkbox (`code_use`)
  - Item type dropdown (`item_type`)
  - Order-to standard dropdown (`order_to_standard`)
  - Marking required checkbox (`marking_required`)
  - Purchaser requires MTR/CMTR checkbox (`purchaser_requires_mtr`)
  - MTR Required checkbox (`mtr_required`) with policy lock behavior
- Material selector panel includes:
  - Spec system dropdown (ASME vs ASTM)
  - Searchable material spec dropdown (sorted by spec number)
  - Grade/Class dropdowns when present
  - UNS typeahead + UNS auto-populate
  - ASTM equivalency info when ASTM selected
- Dynamic form renderer builds controls from `ordering_fields[]` and `input_type`.
- PO preview panel supports live regeneration and copy-to-clipboard.
- Export writes both:
  - structured JSON export
  - plain text PO output (`.txt`)

## Current implementation architecture
- Data loading + validation:
  - `PoApp.Core/Services/NormalizedAsmeDataLoader.cs`
  - validates required record fields and schema shape
- Rules engine:
  - `PoApp.Core/Services/GlobalPolicyEngine.cs`
  - supports `code_use == true/false` and `governing_standard IN/NOT IN <enum>`
- PO composition:
  - `PoApp.Core/Services/PurchaseOrderBuilder.cs`
  - emits 4-section PO text + structured export payload
- Required field checks:
  - `PoApp.Core/Services/RequiredFieldValidator.cs`
- Desktop wiring:
  - `PoApp.Desktop/ViewModels/MainViewModel.cs`
  - `PoApp.Desktop/MainWindow.xaml`

## Configuration
- Desktop app resolves files by searching upward for:
  - `data/asme_po_data_imperial_v4.jsonl`
  - `data/asme_po_schema_imperial_v4.json`
- Build instructions reference:
  - `data/CODEX_BUILD_INSTRUCTIONS_ASME_PO_ASSISTANT_IMPERIAL_V4.md`
- `PoApp.Ingest.Cli/appsettings.json` PDF settings remain for legacy ingest workflows only.

## App data/output
- Active assistant inputs:
  - `data/asme_po_schema_imperial_v4.json`
  - `data/asme_po_data_imperial_v4.jsonl`
  - `data/CODEX_BUILD_INSTRUCTIONS_ASME_PO_ASSISTANT_IMPERIAL_V4.md`
- App export output (via UI Export button):
  - `<chosen-file>.json`
  - `<chosen-file>.txt`
- Legacy ingest/corpus outputs are archived in:
  - `old_data/data/`
  - `old_data/sectionII_partA_data_digitized/`

## Open questions
- Should `required_when` graduate from display hint to fully evaluable expressions?
- Do we want stricter typed validation for `input_type` (number, enum, units) before export?
- Should user defaults (code use, governing standard, export folder) persist between sessions?

## Parsing notes
- Current desktop assistant does not parse PDFs directly; it consumes normalized JSONL records.
- Legacy PDF parsing and OCR workflows remain available in scripts and `old_data/` history.
- `PoApp.Core/Services/OrderingInfoExtractor.cs` remains for legacy/compatibility test coverage.

## UI data flow (current behavior)
- Select context (`code_use`, `governing_standard`) and spec (`asme_spec`).
- ViewModel evaluates global policy and applies/locks `mtr_required` when rules match.
- Dynamic ordering fields are rendered from `ordering_fields[]`.
- Required fields without `required_when` must be filled before export.
- Generated PO includes:
  - Line Item Header
  - Ordering Requirements
  - Supplementary Requirements
  - Compliance Notes

## Agent autonomy (standing instruction)
- The agent may run commands, edit files, refactor code, commit, and push without asking.
- Ask before changing target framework, UI tech, database choice, adding cloud services, or changing parsing strategy materially.
- Do not commit build artifacts or copyrighted PDF content.

## Next steps
- Implement full `required_when` expression evaluation (currently shown as "Required when applicable").
- Add stronger type-aware input validation for `number`, `number_with_unit`, and `enum` patterns.
- Improve spec picker UX (faster filtering, keyboard-first search, optional pinned/favorites list).
- Add settings persistence for user defaults (governing standard, code use, export path).
- Expand supplementary requirements behavior (SR-specific purchaser prompts and richer catalogs).
- Add a release checklist for packaging desktop app + bundled normalized data updates.

## Materials coverage snapshot (normalized dataset)
- Snapshot date: 2026-02-05
- `global_policy` records: 1
- `spec_definition` records: 123
- `material_index` records: 131
- Specs with at least one `ordering_fields` item: 104
- Specs with zero `ordering_fields` items: 19
- Specs with non-empty `rules` arrays: 11

## Quality & testing status
- Current test status: `dotnet test PoApp.Tests` passes (10 tests total).
- Covered areas:
  - legacy ordering extractor behavior
  - normalized JSONL loader + validation
  - global policy rule evaluation
  - PO builder/export payload and required-field validation
- Next quality steps:
  - integration tests for full normalized dataset load and export round-trip
  - UI automation/stress tests (FlaUI)
  - optional stricter analyzer policy once warning baseline is stable
