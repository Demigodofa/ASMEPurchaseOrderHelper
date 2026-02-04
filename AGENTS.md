# Repository Guidelines

## Project Structure & Module Organization
This is a .NET solution organized by project:
- `PoApp.Core/` for domain and shared logic.
- `PoApp.Infrastructure/` for data access and EF Core integration.
- `PoApp.Ingest.Cli/` for the command-line entry point.
- `PoApp.Tests/` for xUnit-based unit tests.
- `PoApp.slnx` as the solution file to build the full workspace.

## Build, Test, and Development Commands
- `dotnet build PoApp.slnx` builds all projects in the solution.
- `dotnet run --project PoApp.Ingest.Cli` runs the CLI application.
- `dotnet test PoApp.Tests` executes the test project.
- `dotnet test PoApp.Tests --collect:"XPlat Code Coverage"` enables coverlet coverage collection.

## Coding Style & Naming Conventions
- C# defaults apply: 4-space indentation, PascalCase for types/methods, camelCase for locals/fields.
- Nullable reference types are enabled; avoid `null` unless the type is nullable.
- Keep filenames aligned with primary type names (e.g., `OrderService.cs`).

## Testing Guidelines
- Framework: xUnit (`PoApp.Tests/`).
- Follow current layout: one test project with files like `UnitTest1.cs`.
- Prefer descriptive test class names ending in `Tests` and method names like `Should_DoThing`.

## Commit & Pull Request Guidelines
- Git history only shows `Initial commit`, so no established convention yet.
- Recommended: imperative, short summaries (e.g., "Add order parser").
- PRs should include a short description, testing notes, and any relevant CLI output or screenshots.

## Configuration & Data
- EF Core is included in `PoApp.Infrastructure/`; keep connection strings and secrets out of source control.
- For local experiments, prefer `appsettings.Development.json` (not committed) and document any required keys in PRs.

## Source Artifacts & Truth Workflow
- Originals live in `inputs/originals/` (gitignored); never overwrite or delete originals.
- Keep `inputs/originals_manifest.json` updated with hashes and source tags.
- The overlay/consensus truth workflow is additive; do not overwrite the existing corpus while building it.
- Stage 0 script: `scripts/build_page_packets_stage0.py`.
- Stage 0 (DOCX) script: `scripts/build_docx_packets_stage0.py`.
- Stage 1 script: `scripts/align_page_packets_stage1.py`.
- Stage 1b script: `scripts/quilt_chunks_stage1b.py`.
- Stage 1c script: `scripts/lock_chunks_stage1c.py`.
- Stage 1d script: `scripts/classify_chunk_variants_stage1d.py`.
- Stage 1e script: `scripts/promote_chunks_stage1e.py`.
- Stage 1f script: `scripts/build_review_queue_stage1f.py`.
- Stage 1g script: `scripts/build_review_queue_with_subsections_stage1g.py`.
- Stage 1h script: `scripts/build_review_collapse_map_stage1h.py`.
- Stage 1i script: `scripts/build_review_top_groups_stage1i.py`.
- Stage 1j script: `scripts/build_review_approval_templates_stage1j.py`.
- Stage 1k script: `scripts/preview_approval_propagation_stage1k.py`.
- Stage 1l script: `scripts/apply_approved_groups_stage1l.py`.
- Comparison script: `scripts/compare_corpus_report.py`.
- Review worksheet script: `scripts/build_review_worksheet_stage1m.py`.
- Boundary fix list script: `scripts/build_boundary_fix_list_stage1n.py`.
- Boundary fix override script: `scripts/apply_boundary_fix_overrides.py`.
- TOC SA-451+ extraction script: `scripts/toc_pass8c_sa451_end.py`.
- TOC SA-451+ index script: `scripts/toc_index_pass10b.py`.
- Spec corpus export with overrides script: `scripts/export_spec_corpus_with_overrides.py`.
- Footer OCR labeling script: `scripts/footers_ocr_label_pages.py`.
- Footer map alignment script: `scripts/align_footer_maps.py`.
- Stage 2 script: `scripts/merge_page_packets_stage2.py`.
- Stage 3 script: `scripts/visual_qa_stage3.py`.
- Stage 4 scripts: `scripts/build_best_text_stage4.py`, `scripts/export_spec_corpus_stage4.py`.
- Stage 4 helpers: `scripts/build_manifest_stage4.py`, `scripts/build_identity_alignment_stage4.py`, `scripts/spec_range_from_headers_stage4.py`.
- ABBYY DOCX sources are reference-only for QA unless explicitly merged; greyscale DOCX is excluded from consensus merges due to low alignment quality.
