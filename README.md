# ASMEPurchaseOrderHelper

PC UI tool to help purchasing agents generate correct ASME purchase orders. The app will extract ASME material requirements from OCR-processed PDFs and store structured metadata locally for fast lookup and form auto-population.

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
