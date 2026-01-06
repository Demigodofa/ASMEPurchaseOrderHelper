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

## Key challenges
- Reliable extraction from scattered PDF content (layered/iterative approach).
- Local storage that stays fast and responsive as data grows.

## Planned UI
- WPF desktop interface (single-pane, already roughed out).
- Windows 10/11 only.
- Mix of search, auto-populate, and dropdowns (to be finalized after data ingestion).

## Suggested approach
- Parsing: staged extraction (start with a minimal set of fields, expand coverage).
- Storage: structured local database for fast lookups (likely SQLite).
- Validation: enforce required ASME PO fields per material.
- Data location: store the user data file in `%LocalAppData%\ASMEPurchaseOrderHelper\` for write access and easy updates.
- Updates: ship a new EXE + bundled data; on run, migrate/replace the local data file if newer.
- Data layout (to keep it fast and non-brittle):
  - `Materials` table: `SpecDesignation`, `SpecPrefix`, `SpecNumber`, `AstmSpec`, `AstmYear`, `Category`, and other core fields.
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

## Open questions
- Do we want a formal data schema now, or evolve it as we ingest?
- What is the minimum set of fields needed for a first usable version?
