# Codex Build Instructions — ASME PO Assistant (Imperial V4)

Date: 2026-02-05

## Files (Data Contract)
Use:
- `./data/asme_po_data_imperial_v4.jsonl`
- `./data/asme_po_schema_imperial_v4.json`

The JSONL contains:
- 1 `global_policy` record
- N `spec_definition` records (ASME Section II ordering requirements)
- N `material_index` records (Spec ↔ Grade/Class ↔ UNS lookup)

**Do not hardcode specs/grades/classes/UNS in code.** Everything must come from JSONL.

## What V4 Adds (Requested Features)
1) **Blank dropdown → pick A or SA**
2) If **ASTM (A)** selected: auto-populate an info line:
   - `Equivalent to ASTM <astm_identical>` (from `spec_definition.astm_identical` for the matching SA spec)
3) **Material dropdown** not jumbled:
   - Sort by numeric `spec_base` then alpha suffix (e.g., 36, 53, 105, 106, 134...)
4) **Typeahead** search for material spec (search spec number + common text)
5) **Grade dropdown** if grades exist for chosen spec
6) **Class dropdown** if classes exist for chosen spec
7) **UNS auto-populate** from material_index mapping
8) Allow **UNS-first workflow**:
   - user types UNS (e.g., K03006) → app finds matching `material_index` entry → sets Spec + Grade/Class automatically
9) After spec/grade/class resolved, render **Section II ordering requirements** (`spec_definition.ordering_fields`) dynamically.

## Key UI Model (the "Material Selector" panel)
Create these controls (left side):
- Dropdown: `spec_system` (blank → pick **ASME (SA/SB)** or **ASTM (A/B)**)
- Searchable dropdown: `material_spec` (displays `SA-106` or `A106` depending on system)
- Dropdown (optional): `grade` (only if `material_index.grades` not empty)
- Dropdown (optional): `class` (only if `material_index.classes` not empty)
- Textbox (optional alternative input): `uns_search` (typeahead; when chosen, it drives spec+grade+class)
- Read-only: `uns_number` (autofilled once selection is resolved)
- Read-only: `astm_equivalency_info` (shown when ASTM selected and matching SA spec has `astm_identical`)

### Mapping logic
Build an in-memory index at startup:
- `spec_def_by_sa`: key `SA-###` → spec_definition
- `mat_by_base`: key `spec_base` → material_index
- `uns_to_candidates`: key `UNS` → list of (spec_base, grade, class)

When user selects:
1) **System**
   - ASME => prefer `material_index.spec_asme`
   - ASTM => prefer `material_index.spec_astm` (if null, still allow but warn: "ASTM designation not available in index")
2) **Material spec**
   - Convert selection to `spec_base` (e.g., SA-106 → "106", A106 → "106")
   - Load `material_index` for that base
   - Show grade/class dropdowns only if options exist
3) **Grade/Class**
   - Select the best matching `grade_class_uns` row and set UNS
4) **UNS-first**
   - When user types a UNS and chooses one candidate:
     - set `spec_base`
     - set `spec_system` default to ASME if `code_use==true`, else keep user choice
     - set `material_spec` (SA-... if ASME else A...)
     - set grade/class accordingly
     - set UNS read-only

### ASTM equivalency info
If system == ASTM:
- Find the matching SA spec_definition by converting A### → SA-###
- If `astm_identical` exists, show: `Equivalent to ASTM <astm_identical>`
- If not found, show nothing (do NOT guess)

## Section II Ordering Requirements (Dynamic)
After spec is resolved to an **ASME spec** (SA-###):
- Load `spec_definition` for that SA spec.
- Render `ordering_fields` exactly as defined (no generic templates).
- Validate required fields; block Export/Copy until complete.

If system is ASTM but `code_use==true`:
- Force the internal `selected_spec_for_requirements` to the SA spec (because Section II ordering rules are for SA).
- Still show the ASTM label for user clarity, but requirements come from SA spec_definition.

## Sorting (not jumbled)
For material dropdown:
- Sort `material_index` records by:
  1) numeric part of `spec_base` (int if possible)
  2) then any suffix alpha (e.g., "213" before "213a" if present)
- Display label based on system:
  - ASME: `spec_asme` if present else `SA-<spec_base>`
  - ASTM: `spec_astm` if present else `A<spec_base>`

## Output requirements
In PO output header include:
- If ASME selected: `Material: SA-### (Title...)`
- If ASTM selected: `Material: A### (ASTM). Equivalent to ASTM <astm_identical> (info)`
- If UNS was used: add a line `UNS: <uns>`

## Notes about the provided UNS index
The UNS/spec/grade/class mapping in V4 is sourced from the uploaded PDF table (QW/QB-422). It is a lookup index and does not replace Section II ordering requirements.
