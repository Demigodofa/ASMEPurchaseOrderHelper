# Codex Build Instructions — ASME PO Assistant (WPF/.NET)

Date: 2026-02-04

## Goal
Build a desktop GUI that:
1) Loads **normalized_asme_partA_specs.jsonl** (JSONL records).
2) Lets a user create an ASME-style Purchase Order line item by selecting a spec and filling required fields.
3) Applies global policy rules for Code Use, with **B16 marking-only exemptions**.
4) Outputs a **clean Purchase Order text block** (copy/paste) and a structured JSON export.

## Inputs / UI Controls (Minimum)
### Top-level PO Context
- Checkbox: **Code Use (ASME construction)** -> `code_use` (bool)
- Dropdown: **Governing standard** -> `governing_standard` (string)
  - Options: 
    - "ASME BPVC Section II material"
    - "ASME B16.5"
    - "ASME B16.9"
    - "ASME B16.11"
    - "ASME B16.34"
    - "Other (specify)"

### Spec Selector
- Searchable dropdown: **ASME Spec** populated from `record_type="spec_definition"` records `asme_spec`.
- Display title + ASTM identical (if present).

### Dynamic Spec Form
Render fields from `ordering_fields[]`:
- `prompt` is the label
- `input_type` determines control:
  - text -> TextBox
  - number -> Numeric input
  - enum -> ComboBox (if `options` present, else TextBox)
  - boolean -> CheckBox
  - multi_select -> multi-select list
  - sr_select -> checkbox list for SR codes (if SR catalog present)
  - number_with_unit -> number + units dropdown (use `units`)

Required handling:
- If `required == true`: field must be filled.
- If `required_when` is non-null: treat as conditional; show helper UI "Required when applicable" (do not hard-fail without a real expression).

## Rules Engine
### Global Policy Record
Read the JSONL line where `record_type=="global_policy"`.
Implement its rules using:
- `if` string evaluation limited to:
  - `code_use == true/false`
  - `governing_standard IN/NOT IN <enum-name>`
- `then` actions:
  - set a boolean flag like `mtr_required`
  - add PO notes

Behavior required:
- When `code_use==true`:
  - If governing_standard is NOT in B16_MARKING_ONLY -> force `mtr_required=true` and add PO note.
  - If governing_standard IS in B16_MARKING_ONLY -> set `mtr_required=false` and add PO note stating marking-only policy.

UI enforcement:
- Display `mtr_required` as a locked checkbox when the global policy rule applies.
- If user attempts to change it when locked: show warning.

## Purchase Order Output (Clean Text)
Generate output with 4 sections:

1) **Line Item Header**
   - "Material: <ASME Spec> (<Title>)"
   - If `astm_identical` exists: "ASTM Identical: <...>"

2) **Ordering Requirements**
   - For each ordering field that is filled:
     - "<prompt>: <value>"

3) **Supplementary Requirements**
   - If SRs selected:
     - "Supplementary Requirements: S1, S5, ..."
     - Include any SR-specific purchaser_must_specify prompts (if present in SR catalog).

4) **Compliance Notes**
   - Include global-policy notes:
     - If `mtr_required==true`: "Provide MTR/CMTR (certified test report) with shipment."
     - If B16 marking-only: "Marking requirements per ASME B16.<...>; MTR not required by this policy."
   - Include any spec `rules[]` text as informational notes.

Also output JSON:
- `po_context` (code_use, governing_standard, mtr_required)
- `spec` (asme_spec, title, astm_identical)
- `field_values` (key/id -> value)
- `selected_supplementary_requirements` (codes)

## File Locations (assume relative to solution)
- Data file: `./data/normalized_asme_partA_specs.jsonl`
- Schema: `./data/normalized_asme_po_schema.json`

## Quality Requirements
- Never hardcode specs in code; always read JSONL.
- Searchable spec dropdown.
- Copy-to-clipboard button for PO text output.
- Export button: saves JSON and PO text to disk.