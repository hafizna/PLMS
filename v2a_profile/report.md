# PLMS v2a — source profiling report

Generated read-only on `2026-08-21`. No source workbook, database, or UI was changed.

## Coverage

- UPT workbook: **22/22 physical tabs** mapped.
- Logical UPT sources: **17/17** — AR, BUSPRO, CBF, CBF&CCP, CCP, DIFF Pilot, DV, FR_OCR, KAPASITOR, LCD+DIST, OCR, OCR KOPEL, Pivot Table 1, Rekap, Rekap1, SZP, Synchro.
- Official workbook: **7/7 physical tabs** profiled; DV remains an explicit helper.
- Relay candidates: **1504** exact-source rows/device slots.
- Official history events: **292** meaningful rows.
- Cross-sheet exact-identity groups: **199**; metadata conflicts requiring review: **3**.
- Review queue rows: **716** — COORDINATION_CLASS_REVIEW: 18, IDENTITY_METADATA_CONFLICT: 3, LOW_IDENTITY_CONFIDENCE: 693, SPECIAL_LAYOUT_PARSER: 2.

## Coordination classification (candidate rows)

- `AUXILIARY`: 847
- `GRADED`: 408
- `REVIEW`: 18
- `UNIT`: 231

`REVIEW` is not silently coerced into a production class. It currently covers **18**
candidate devices in capacitor UNBALANCE and UVR/OVR blocks because the v2 prompt does not classify
those labels explicitly.

## Identity rule

1. A meaningful normalized serial number creates `SERIAL|...` (HIGH confidence).
2. Without serial, exact normalized GI + bay + manufacturer + model + relay role creates `ASSET|...`
   (MEDIUM when complete, otherwise LOW).
3. Function type is deliberately excluded from the identity key: one physical IED can appear in LCD,
   DIST, AR, CBF, or other function sheets.
4. No fuzzy matching is performed. Conflicting exact groups are emitted to `identity_overlaps.csv`.

## Explicit v2b parser work

- Unpivot `FR_OCR` (143-column form response) with source-column provenance.
- Parse grouped multi-row settings in `CBF&CCP`.
- Convert setting columns to long form while retaining workbook/sheet/row/column/header/hash.
- Resolve the capacitor `CAP_UNBALANCE` and `UVR_OVR` coordination classification.
- Link official events to relay identities and determine `is_current` by effective date without overwrites.
- Review LOW-confidence identities and all metadata conflicts before database load.
