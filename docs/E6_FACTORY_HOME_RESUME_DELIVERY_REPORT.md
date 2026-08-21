# E6 Factory Home and Resume Delivery Report

## Verdict

**E6 Factory Home / Resume: PASS / PENDING E5–E7 FINAL MERGE.** Production now defaults to the real Product API adapter. Development fixture data is isolated behind the conjunction of development mode and the explicit `VITE_PROTEUS_DEMO=true` opt-in. Factory Home remains a source-derived navigation surface and adds no runtime control capability.

## Focused evidence

| Gate | Result |
| --- | --- |
| TypeScript project check | PASS |
| Frontend Vitest | 6 files, 37 tests passed |
| Production build | PASS |
| oxlint | 0 warnings, 0 errors |
| E5 Product API/read model real PostgreSQL gate inherited | 48 tests passed before E6 implementation; source facts remain unchanged |

The E6 contract test verifies the production selector returns `productApiAdapters()`, that fixture selection requires both development mode and the explicit demo flag, and that the old `VITE_PRODUCT_API_READS` override is absent. It also verifies that the Entry Draft UI retains and reuses its first idempotency key after an unknown outcome.

## Boundary confirmation

E6 adds no database migration, no Project/Task/dependency/VerificationPlan direct write, no Product aggregate, no Scheduler/Worker/Execution control, no Gate decision path, no Evidence or Recovery mutation, no provider configuration, and no E2.x live smoke. E7 is not entered by this report.
