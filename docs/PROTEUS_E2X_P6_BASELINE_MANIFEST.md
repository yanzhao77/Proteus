# Proteus E2.x/P6 Baseline Manifest — Final Reseal

> **Purpose:** This non-self-referential manifest inventories the E1/E2/E2.x/P6/Golden Todo/frontend files selected for this delivery commit. It SHA-256 hashes only those commit candidates, excludes itself to avoid self-reference, and records unrelated dirty worktree material as an unhashed `REVIEW_REQUIRED` exclusion list.

## 1. Seal Metadata

| Field | Value |
| --- | --- |
| Repository HEAD | `c5dd19e6c6f7c86cae6ed5ec0910e631d9ec72c5` |
| Branch | `e8-production-entry-trial` |
| Generated UTC | `2026-08-21T11:01:24Z` |
| Manifest self-hash | **Excluded intentionally** to avoid self-reference. |
| Commit operation | **Not performed.** This is an inventory, not a staging action. |

## 2. Classification Rules

| Classification | Meaning |
| --- | --- |
| `THIS_CLOSURE` | Files edited for the strict owner-plus-Create/name-cleanup closure, validation-statistic reconciliations, CI prerequisites, and the minimal P5 migration bootstrap deployment repair. |
| `INHERITED_DELIVERY_CANDIDATE` | Existing modified or untracked files that compose the known E1/E2/E2.x/P6/frontend delivery surface. They are listed for a later human commit decision, not newly attributed to this closure. |
| `REVIEW_REQUIRED` | Dirty files excluded from this commit because their relation to the required delivery cannot be proven from pathname and task evidence alone. They are listed without SHA-256 and must not be staged by inference. |

## 3. This Bootstrap Acceptance Closure and CI Follow-up

| SHA-256 | Path | Working-tree state |
| --- | --- | --- |
| `4fdcfefdc2101e7e6240f7346abd2a7e86dfa42d870e66c7a43679bebd9dc5a5` | `.github/workflows/hermes-p5.yml` | modified tracked — post-PR Todo role and Golden Todo runtime bootstrap |
| `3b04004a434ba00810e41ef052a20e9aa2f4bdaa3697fc35893b235117dcdcee` | `hermes-runtime/Dockerfile` | modified tracked — normalize copied migration SQL mode before non-root runtime |
| `8aaa4f966425a664e0c0ef8ab610a3e9c7ecac16e8e885915476490a41c31c90` | `hermes-runtime/src/hermes_runtime/migration_bootstrap.py` | modified tracked — use existing PostgresRuntimeStore migration API |
| `14a14ec59cf739aa9511504e08312d0dce51007011cd2c1ae63570abb36d6145` | `hermes-runtime/tests/test_deployment_baseline.py` | modified tracked — lock migration readability before USER hermes |
| `5eba523d61a7cc6c34114cf7a7fc6c46b6dd6c162b14172e3e441353c9df072c` | `hermes-runtime/tests/test_migration_bootstrap.py` | untracked — bootstrap entry contract coverage |
| `3c4d871538ad2bd80cfa4eaacbabc491d30f407d7f978ff45ea54866cda59f71` | `docs/E2X_LIVE_PROVIDER_SMOKE_DELIVERY_REPORT.md` | untracked |
| `ab05490b6021010d0d63a5d80a6361b6003e486388a782935ce38190bad797b9` | `docs/E2X_PRODUCER_INTEGRATION_DELIVERY_REPORT.md` | untracked |
| `17e84ae952f53e61f62e91dde3673b7d15c0933a5507fc3a81f9bed455ec0947` | `docs/P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DELIVERY_REPORT.md` | untracked |
| `4fc0c646eb018d64ffd3e29e4dece033684852b8af6fa011ad3f71612a0bdc93` | `docs/P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DESIGN.md` | untracked |
| `2e51e85e8a4fd0150c1eeaa8564e6a4ae484843af76cab108184116bedd04bc8` | `examples/golden-todo/tests/conftest.py` | modified tracked |
| `b380c7bcb7908afd3e9f7e342447914b29b7e429210db7a50199a3bceb8d2f81` | `hermes-runtime/src/hermes_runtime/trial/test_database_bootstrap.py` | untracked |
| `bce79ae84c642fb10c587fe8989df22ef9d0bd9aacc25bf0907fa401c5cab06f` | `hermes-runtime/tests/test_p6_autonomous_trial.py` | modified tracked |
| `ad0629f57c14b1f05e3679689dfa5f18c86eafd48cbf68839bfca0e5b4ee8dc2` | `hermes-runtime/tests/test_p6_todo_database_bootstrap.py` | untracked |

## 4. Inherited Complete-Delivery Candidates

| SHA-256 | Path | Working-tree state |
| --- | --- | --- |
| `1f840f5887135a3624fd9a1af924cd27677b090d7605b44a5d6d9b7c175c486a` | `docs/E1_ENTRY_DRAFT_CORE_DELIVERY_REPORT.md` | untracked |
| `86352676d847f6b13699513959262d227fb63260a0addb8c8630c704288274a2` | `docs/E1_ENTRY_DRAFT_CORE_RECON_REPORT.md` | untracked |
| `9fe1a61f11a0d5d6807fc3e3c481981fa4192ae69952556dfe420636dbedabe6` | `docs/E2X_LIVE_PROVIDER_SMOKE_RUNBOOK.md` | untracked |
| `7d0726571663abfa21f8814d96cacd892e5a966b1f61637e26f9db9f0cb58d96` | `docs/E2X_PRODUCER_INTEGRATION_DESIGN.md` | untracked |
| `9f8e7081e8ebd9bd40cd18717ca02d3d5d31b5ef23b52f36b82ccf9aef05c987` | `docs/E2X_PRODUCER_INTEGRATION_IMPLEMENTATION.md` | untracked |
| `44fc7b34f961f3d306e31b32db958ab23149a8a72a6acf3e6016e3f5c1eee836` | `docs/E2X_PRODUCER_INTEGRATION_RECON_REPORT.md` | untracked |
| `55c3b7ed3ef486482640e0e7a476d15a608de3dc5175c402022b5bcf9bf41897` | `docs/E2_ENTRY_UNDERSTANDING_DELIVERY_REPORT.md` | untracked |
| `1c4b6bfc37bee9600e910dd6f545337433668405d19923bcdcfb2a476e700084` | `docs/E2_ENTRY_UNDERSTANDING_IMPLEMENTATION_V1.md` | untracked |
| `ce367b25c104554225c296f6163e524d9f88e6943e717aaa8f6ebddd891dc792` | `docs/E2_ENTRY_UNDERSTANDING_RECON_REPORT.md` | untracked |
| `81373a838c00d6a5445100bc3d43b7a53370e99a7c10b161d5ad74f974eadfc5` | `docs/ENTRY_RECON.md` | untracked |
| `f6d4ba0757fdd37c2b29e0253ed9e4d167e4b60dfd61d652f06e77fc23d50ad5` | `docs/FH1_READ_MODEL_ADAPTER_DELIVERY_REPORT.md` | untracked |
| `a4c965bac514de12f81fc53528ce82316d51f39d532f38ce2326ac700907b7ee` | `docs/P6_RECOVERY_PERMISSION_DISCREPANCY_RECON.md` | untracked |
| `be01aa5d89192964691e0177c18ee68a54da093a8d4caaf03d7a8cb558127ba0` | `docs/P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md` | untracked |
| `e2d3b90f22409541c44e377c0b5e55c974039a2b82bfed634bc2fe4f99ddf9ee` | `docs/P6_RECOVERY_PERMISSION_REPAIR_DESIGN.md` | untracked |
| `17cb208c0aa88566fa46020ef2069700eaff698d03f2a0917e40f42e9a00ec60` | `docs/PROTEUS_FACTORY_HOME_FRONTEND_ARCHITECTURE_V1.md` | untracked |
| `7b6fdfe3d39c292521c30a8945c9c8638fab7dae2b137e93735e1d5b32f262c7` | `docs/PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md` | untracked |
| `745a0a0b88ea9a65967d699181daeabff85955fa606d012d8baa20a38f6fa528` | `docs/PROTEUS_FACTORY_HOME_TAILWIND_THEME_V1.md` | untracked |
| `7820a101fd28c1435b41aeafac3e06ee0f05ed21880b01b454c168b4ffbf4b48` | `docs/PROTEUS_FACTORY_HOME_UI_STYLE_GUIDE_V1.md` | untracked |
| `39246bea50c4a649e94c8902d64c1ef5705e8f0721fe646c8fa02357803b36a4` | `docs/PROTEUS_LIVE_PRODUCTION_UX_V1.md` | untracked |
| `674eda7a1c4c2c45e0c12de134387075458a46d7a35348ffab34cd85b9a4e08c` | `docs/PROTEUS_PRODUCTION_ENTRY_ARCHITECTURE_V1.md` | untracked |
| `344a2b763417662f90ad7037d875aee8bb55af3678cb4e7882a8ddcb8ad76467` | `docs/PROTEUS_PRODUCTION_ENTRY_IMPLEMENTATION_PLAN_V1.md` | untracked |
| `e4c79b9a5ae16efa6e98ee3776774af0b6f98c33d2551d649029e23228bf9ec7` | `docs/PROTEUS_PRODUCTION_ENTRY_IMPLEMENTATION_READINESS_REPORT.md` | untracked |
| `dc98f0789a62cd3856fcb058284dae78be9800da942ab2abbc0d727d86d8264c` | `docs/PROTEUS_PRODUCTION_ENTRY_UX_V1.md` | untracked |
| `e2dbc2438fded488be534a3edb0713172da3d7db28d17f5244e0c758c7b45020` | `frontend/.env.development.example` | untracked |
| `fe718e7babb14f3cbad2d97f08889b9ce5215ed3fe0e43b2b8cfbfb3b9b844e8` | `frontend/.gitignore` | untracked |
| `b4d344818a1e1bf43997e4744a9153c8eef770c98b58229cd86363dabb85ded4` | `frontend/.oxlintrc.json` | untracked |
| `876be87bc223b0ee24de9dc2d0d71b62f78f8cd1e655d77b4ccdea2055370752` | `frontend/README.md` | untracked |
| `c489ca10e39dee2c944678c7cbe29c05c1464f0d3ad331829be0616dfe292ada` | `frontend/index.html` | untracked |
| `82fc4d57ff6b34909e6f8ef4f2a60cc2f43f1d330a4615e4f92f9e51441dff7d` | `frontend/package.json` | untracked |
| `ef2aef367e00b7fdd17d4d64a5752074e987704299bf3e2afca99fd2cd82178e` | `frontend/pnpm-lock.yaml` | untracked |
| `68fac9e49f1efae93cbcb642ed05fd127f6caf05ecc0686e4aae3be93bbdb1e0` | `frontend/postcss.config.cjs` | untracked |
| `61bc9a161de58248288e6905425d7180f0624c2865007b97d763fdac12043a66` | `frontend/public/favicon.svg` | untracked |
| `b45fa506195cfcdef406ba9f0c77b36ddc1a7c224040926ec70abc2fdea7b93a` | `frontend/public/icons.svg` | untracked |
| `8ad2e8af9cd2ca5fcd7511754ff9342b6b2c1de797553041c4a6b632db41f7b1` | `frontend/src/App.test.tsx` | untracked |
| `1ab01a10c0fea874de68afef1b4230692abb04048e8dcc701a1fc926d6605aaa` | `frontend/src/App.tsx` | untracked |
| `88373435dec7e3b4ff01056626185b23e773bd78994617a26045776fefbdca03` | `frontend/src/api/adapters.test.ts` | untracked |
| `530afeca26fc55e4d2041bbf4b68de3fb22a008bc1468fd80a6bd8ede070ebf3` | `frontend/src/api/adapters.ts` | untracked |
| `5b232fc3e607d3db6563fe89eb57f2a8337a49395328bde13035564b03cbd2ac` | `frontend/src/api/fixtureAdapters.ts` | untracked |
| `9788864a7ae3ea8f1f15463514ba2545018fb67b687cf3d4a2afcab1a3441564` | `frontend/src/api/index.ts` | untracked |
| `4e64d28ef8c6428c6e239f0f8132d216cd1ee723ef01928244eedced95ff56d4` | `frontend/src/api/productApiAdapters.test.ts` | untracked |
| `cd73ec4ac5f99fa8ebec6d2beb3263cb10657140d7b03de25018ca1968eb877b` | `frontend/src/api/productApiAdapters.ts` | untracked |
| `dbe6271a8fab806a32292ecc566994b5782d551bda4f3f750fc9a7c6ae0d7272` | `frontend/src/contract.test.ts` | untracked |
| `2b91f6f3bc360041371947a78c768de59ea45df066a7e6d0ef58b5250e4c7a68` | `frontend/src/main.tsx` | untracked |
| `793c5c277e12ed6ea91ca1743b08fd0b5b6b4a342f36369535d20a07d7a14355` | `frontend/src/models.ts` | untracked |
| `da1071a3487bac26277087bba76e805d123299818fc995439719a5efaa7b9163` | `frontend/src/styles/index.css` | untracked |
| `91a3c8962a0edcb956206a501d943fe99e1c78c6d4d8b5c9a948a3362c75978c` | `frontend/src/test/setup.ts` | untracked |
| `437f9333e6dd79f82cf1427cf540cdfab2d18110bf5af6476319cab1cd803df3` | `frontend/src/theme.test.ts` | untracked |
| `5d9f2ae5892685f9325aaee283404f6b26cd0b9927211596dc6cc2f1e209a8df` | `frontend/tailwind.config.ts` | untracked |
| `2804b10bdf9413b5f36f9ec640fdbe2a538f802ad60014dd94fd6f8b5f63f07e` | `frontend/tsconfig.app.json` | untracked |
| `770b4140bbb581e2dfd9ea9946ffc9c75a1d86ba7d2db5f77c83e37cbdf9d808` | `frontend/tsconfig.json` | untracked |
| `d366cc0827139db39c61815f22491bbfda56c654354a42ad7795143d314e45e8` | `frontend/tsconfig.node.json` | untracked |
| `f69e48fd28c722ca7c6a48d70ffa66cf263e1635134e4597792787d181a03b4c` | `frontend/vite.config.ts` | untracked |
| `5d3ef2589190e844ffac1849f7cc47a9a4dea697dc6437bc2eb276ac0fabdad2` | `hermes-runtime/migrations/0025_e1_entry_draft_core.sql` | untracked |
| `a26032eb08d3979199f4590e4f7832d52c47ea4998947d59ca7636a9abb90970` | `hermes-runtime/migrations/0026_e2_entry_understanding.sql` | untracked |
| `c71a112e3a5ef4ad0fa4a4af4f846bff7680c2c742fb3240639de5661bafaaa3` | `hermes-runtime/migrations/0027_e2x_producer_provenance.sql` | untracked |
| `f44cc6f6d20fd7afea583ed967057d9fcda38d2419376b9b86599d1295bea678` | `hermes-runtime/migrations/0028_p6_recovery_runtime_least_privilege.sql` | untracked |
| `7cf67da42378ed4b252529c1515beb5e3b0c25567cb2df23413751d10bad0d9c` | `hermes-runtime/scripts/e2x_live_provider_smoke.py` | untracked |
| `9e928cf5e5336bf0d028a019907ed1edbd3656e88d61cb6e34f59f3b4cab0e30` | `hermes-runtime/src/hermes_runtime/api_main.py` | modified tracked |
| `990163cbdca2608474f1565c10ad9a7d457fc105a1080174c4b407a23a9a5c13` | `hermes-runtime/src/hermes_runtime/application/entry_draft_api.py` | untracked |
| `adb8e5b2fdac14f1e56bb59c6c3ba3e2a84e60a7be08d209c2ed75886c6ea39b` | `hermes-runtime/src/hermes_runtime/application/entry_understanding_api.py` | untracked |
| `df692928211b3c02d2076de60aee1a8843a1556219ef166be58b50c0eab53446` | `hermes-runtime/src/hermes_runtime/application/factory_home_read_model.py` | untracked |
| `75f86464264e680c7ee668cf81fa4b784b163e624f97d44971d979c2ae3eb57a` | `hermes-runtime/src/hermes_runtime/application/factory_workspace_ui.py` | untracked |
| `437cc867291327211b480885dcbbcf0b593f210866e5be81b1dc247431209884` | `hermes-runtime/src/hermes_runtime/application/product_api.py` | modified tracked |
| `83d28d70225a94295ea0dc0374e5f765ea04053d95a0ec68c28e69d8f5a59511` | `hermes-runtime/src/hermes_runtime/domain/entry_draft.py` | untracked |
| `0f99b79473e2a6a9ab848ec497ed0e1e6682789bab86ce1e35f5f5505a11f760` | `hermes-runtime/src/hermes_runtime/domain/entry_understanding.py` | untracked |
| `5ec2765253592709f2433110a3d70966030a1f187bc97cb926a635dfbb447a88` | `hermes-runtime/src/hermes_runtime/domain/product_api.py` | modified tracked |
| `bcad28c39ed1879dbc6cc6e9b026a33359f03a6895fedf26aee63f70a916ff16` | `hermes-runtime/src/hermes_runtime/domain/understanding_producer.py` | untracked |
| `adeef3e99edbde689d6129bc14b59eef1c19c6ff033ca362eb18d17516dcbe79` | `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | modified tracked |
| `0050a8c928fc20fb09ec21f7017e43fbf2d6908e5dafc14b5a454726394f18be` | `hermes-runtime/src/hermes_runtime/infrastructure/openai_compatible_understanding_provider.py` | untracked |
| `f46c65937ea921a2a66a1f1768cdf98f48448966f529e0b0468b9c28e29d79f1` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_draft.py` | untracked |
| `043648bc92ce94ec29c6bd5224d4ee9a508e5e3565d75132b551d9f29a23448d` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_understanding.py` | untracked |
| `440bef63b2d74cff73b5f82e76b574b1effd152bd05dd8e5da96602cd14478eb` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_factory_home_read_model.py` | untracked |
| `5e69fa60309adcc58ddde329bdb08e0cefdc505e945b26a8cd1481d19738b9a3` | `hermes-runtime/src/hermes_runtime/infrastructure/understanding_provider_registry.py` | untracked |
| `460331a448b1ef367846e1648e0101fdc8a1fc220eefb508ef885018e4d6dd69` | `hermes-runtime/tests/test_e2x_fastapi_error_envelope.py` | untracked |
| `508e4ecf066c23710dfb4c795033e080ece92343a0406e0128dd09d71063cc40` | `hermes-runtime/tests/test_e2x_live_provider_smoke.py` | untracked |
| `72c8f13891c93272d10425e51bfc49a8f84f588504943f812d411c5bffe6f3ef` | `hermes-runtime/tests/test_e2x_provider_adapter.py` | untracked |
| `78b7b8780597766e3d9508a5f7ef56fb12739891d59d5c9c774f78e97f018bc3` | `hermes-runtime/tests/test_entry_draft_core.py` | untracked |
| `4afac5b15a7de4ac8849f6c1e63ba089b5d4aa2e6c945a51cf0ccd345d847add` | `hermes-runtime/tests/test_entry_understanding_core.py` | untracked |
| `ec4ed8a8551077170d08a02a0a906a3e9ea79158e1c203171cf956db06c3b7df` | `hermes-runtime/tests/test_factory_home_identity_scope.py` | untracked |
| `855df2838b325d83297a5b94af2fa8ad4eb8f8e6abb69e4b40834f0714b62490` | `hermes-runtime/tests/test_factory_home_read_model.py` | untracked |
| `e2d7cc717561dd112641553122d47f34aee88d48e849dc3f426346b1069a211a` | `hermes-runtime/tests/test_factory_workspace_ui.py` | untracked |
| `d5b89979cb2ece6094f4e36ec944c2860e9a26c43f82f78a30004638e33b7a0b` | `hermes-runtime/tests/test_p6_recovery_runtime_least_privilege.py` | untracked |

## 5. Review-Required Exclusion List

> The following dirty worktree material is **not part of this commit**. It is intentionally retained in place without SHA-256 entries so a clean PR checkout never requires excluded files for manifest verification.

| Path | Working-tree state | Commit treatment |
| --- | --- | --- |
| `docs/P6_MINIMUM_IMPLEMENTATION_ROADMAP.md` | untracked | Excluded — review required. |
| `docs/Proteus Production Entry Implementation Readiness Report.md` | untracked | Excluded — review required. |
| `docs/assets/authority_flow.png` | untracked | Excluded — review required. |
| `docs/assets/factory_home_state_machine.png` | untracked | Excluded — review required. |
| `docs/assets/plan_mutation_flow.png` | untracked | Excluded — review required. |
| `docs/assets/production_entry_flow.png` | untracked | Excluded — review required. |
| `docs/ui/proteus_factory_effects.css` | untracked | Excluded — review required. |
| `docs/ui/proteus_factory_tailwind_theme.ts` | untracked | Excluded — review required. |

## 6. Required Delivery Coverage

| Delivery area | Inventory treatment |
| --- | --- |
| E1 Entry Draft | Included as `INHERITED_DELIVERY_CANDIDATE`: migration `0025`, entry-draft application/domain/store/tests and related reconciliation/delivery records. |
| E2 Understanding | Included as `INHERITED_DELIVERY_CANDIDATE`: migration `0026`, understanding application/domain/store/tests and related records. |
| E2.x Producer | Included as `INHERITED_DELIVERY_CANDIDATE`: migration `0027`, provider/provenance/smoke implementation/tests and E2.x records; this closure updates only current verification statistics. |
| P6 least privilege | Included as `INHERITED_DELIVERY_CANDIDATE`: migration `0028`, Recovery repair evidence and runtime-role test. No P6 authority code is modified by this closure. |
| Golden Todo bootstrap | Included as `THIS_CLOSURE`: helper, fixture, lifecycle, narrow tests, and current design/delivery records. |
| Frontend delivery | Every untracked `frontend/**` file is listed as `INHERITED_DELIVERY_CANDIDATE`; no frontend file is modified by this closure. |

## 7. Final Verification Baseline

| Check | Current result |
| --- | --- |
| Cleanup-authenticity/bootstrap PostgreSQL/Golden Todo | **13/13 PASS** in `2.830 s`; factory-issued, evidence-tamper, OID-replacement and owner-mismatch closure; direct Golden Todo **9/9 PASS**. |
| P6 permission/runtime-role | **6/6 PASS** in `3.777 s`. |
| P6 focused permission/runtime-role/Todo/autonomous | **20/20 PASS** in `125.88 s` on this E3 disposable PostgreSQL acceptance. |
| Stage A2 execution-prepare convergence | **PASS** — fresh `0001→0032` metadata audit; canonical sandbox guard callsite; P6 bootstrap/autonomous **14/14 PASS** in `105.804 s`. |
| Focused E1/E2/E2.x/FH-1/FastAPI/OIDC/Product API | **86/86 PASS** in `4.309 s`. |
| E3 formal PostgreSQL authority / migration bootstrap | **8/8 PASS** in `1.17 s`; deterministic, replay, freshness, immutability, isolation, grants and negative side effects verified. |
| no-DB discovery (including conditional E8 test) | **705 run, 438 skipped, 0 failures** in `1.233 s`. |
| Full Runtime regression | **705 run, 12 skipped, 0 failures** in `429.306 s` on Stage B fresh PostgreSQL 16 acceptance. Historical sealed baselines remain historical evidence. |
| Frontend Vitest/build/lint | **40/40 PASS** in `1.14 s` / PASS in `320 ms` / `0` warnings and `0` errors. |
| E8 same-project Production Entry Trial | **PASS** — real E4 materialization → P6 recovery → E7 snapshot/feed, `1` test in `42.901 s`; disposable DB cleanup verified. |
| Live provider smoke | **PASS — NON-PRODUCTION**; one authorized local Docker Product-API-only run consumed `9 / 9` requests, generated one governed Understanding and replayed the same idempotency key without a new revision. Full runtime was not re-run. |

## 8. Current-versus-Historical Documentation Matrix

| Document class | Documents | Statistic authority treatment |
| --- | --- | --- |
| **Current Verification Authority** | This manifest only | The numbers in Section 7 are the sole repository-wide current E2.x/P6 baseline. |
| Synchronized current mirrors | `E2X_PRODUCER_INTEGRATION_DESIGN.md`, `E2X_PRODUCER_INTEGRATION_IMPLEMENTATION.md`, `E2X_PRODUCER_INTEGRATION_DELIVERY_REPORT.md`, `E2X_LIVE_PROVIDER_SMOKE_DELIVERY_REPORT.md`, `P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DESIGN.md`, `P6_GOLDEN_TODO_DATABASE_BOOTSTRAP_DELIVERY_REPORT.md` | These documents explicitly point here and mirror Section 7; they do not establish independent current numbers. |
| Historical phase-local snapshots | `P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md`, `E1_ENTRY_DRAFT_CORE_DELIVERY_REPORT.md`, `PROTEUS_FACTORY_HOME_IMPLEMENTATION_V1.md`, `PROTEUS_PRODUCTION_ENTRY_IMPLEMENTATION_READINESS_REPORT.md`, `Proteus Production Entry Implementation Readiness Report.md` | Their contemporaneous numbers remain historical phase-local snapshots, **not the current repository baseline**. `P6_RECOVERY_PERMISSION_REPAIR_DELIVERY_REPORT.md` carries this label in-file; this manifest classifies the remaining unmodified historical reports. |

No document is permitted to present a number different from Section 7 as the current repository-wide E2.x/P6 baseline.

## 9. Integrity and Boundary Record

The final seal requires a passing manifest SHA-256 recomputation over all and only the hashed commit candidates, `git diff --check`, scoped secret scan, protected-path audit, and a query proving no `todo_p6_ci_*` database remains. The manifest does not require excluded `REVIEW_REQUIRED` files for clean-checkout verification. This evidence delivery does not include provider credentials, token material, authorization headers, endpoints, DSNs, raw prompts or raw provider responses; it records one sanitized live provider verification.

## 10. Authorized E2.x Non-Production Live Verification

| Field | Value |
| --- | --- |
| Execution UTC | `2026-08-20T03:14:47Z` |
| Release commit | `ebc9e6e8d80ad07a48f8274f7d686444941e0604` |
| Target class | `non-production` |
| Product API requests | `9 / 9` |
| Logical generation / replay | `1 / 1` / `1 / 1` |
| Draft / source revision | `ed-90adc0942dd04299a342c39fde030bbf` / `edr-3f1adc2180ac41e88e98baf90b30b753` |
| Understanding / revision | `eun-5e5bab6b0be543799d2138ec94f985e4` / `eur-b92d2e9fc3ae4711bca70f1d12700852` |
| Provider / model | `openai-compatible` / `deepseek-chat` |
| Provider request identifier | `8555da4d-b22a-4de3-b09b-5026c9ddc53d` |
| Prompt / schema | `v2` / `v1` |
| Usage | `325` input / `117` output / `442` total tokens |
| Latency / retry count | `1805 ms` / `0` |
| Replay | `same_authoritative_result_no_new_revision` |
| Verdict | **PASS — NON-PRODUCTION** |

The runner used only the governed E2 Product API route surface. It created no Proposal, Plan, Project, Task, Execution or P6 side effect. This document retains no token, credential, authorization header, endpoint, DSN, raw prompt or raw provider response. The sealed Full Runtime `575 run / 12 skipped / 0 failures` result is preserved and was not re-run for this evidence update.


## 11. Current Final Status Matrix

> **Current Verification Authority:** This manifest is the sole repository-wide current E2.x/P6 verification authority. The matrix below supersedes no historical record; it resolves only the current-status wording of the synchronized documentation mirrors.

| Status | Current result |
| --- | --- |
| E2.x Repository/Internal Delivery | **PASS** |
| E2.x Live Provider Verification | **PASS — NON-PRODUCTION** |
| E2.x Phase | **COMPLETE / LIVE VERIFIED** |
| P6 Authority Gate | **CLOSED** |
| P6 Functional Revalidation | **PASS** |
| P6 Secret Guard Policy Repair | **PASS — Stage A2; 0031 structured JSONB policy plus 0032 live sandbox callsite convergence; no E8 continuation** |
| E3 Proposal / Master Plan | **PASS** |
| E3 Phase | **COMPLETE** |
| E4 Approval Bridge | **PASS / COMPLETE** |
| E5 Product API / Read Model | **PASS / COMPLETE** |
| E6 Factory Home / Resume | **PASS / COMPLETE** |
| E7 Live Production Integration | **PASS / COMPLETE** |
| E8 Production Entry Trial | **PASS / COMPLETE** — same-project real vertical trial; no E9. |

## 12. Documentation/Metadata-Only Correction Record

This E3 closure preserves all inherited E2.x smoke provenance and the fixed `9 / 9` Product API budget without rerunning smoke or calling a provider. It preserves the E3 delivery's real disposable PostgreSQL Full Runtime result of **586 passed, 12 skipped, 0 failures** in `321.58 s`, P6 `20/20 PASS`, E3 formal PostgreSQL `8/8 PASS`, fresh `0001 → 0029` migration PASS and frontend `35/35 PASS`. This E4 closure additionally records **634 run, 12 skipped, 0 failures**, real PostgreSQL durable matrix `26/26 PASS`, fresh `0001 → 0030` migration PASS, P6 Recovery focused `9/9 PASS`, and frontend `35/35 PASS`; it does not rerun E2.x provider smoke. Historical `575 run / 12 skipped / 0 failures` remains sealed inherited evidence only.

## E4 Approval Bridge Historical Scope

> E4 is complete. Its original no-E5+ boundary describes only the scope of the E4 delivery at that time; it is not a current repository-wide phase status. Section 11 is the unique current final status matrix, and Section 15 records the later E5–E7 closure.

E4 is limited to explicit approval, deterministic lowering, receipt-first durable bridge records and fresh-instance reconciliation through existing ControlPlane child command ports. The sealed real PostgreSQL matrix covers post-commit interruption after Project, Graph and each VerificationPlan child boundary, terminal child rejection, immutable authority facts and direct-DML denial. It introduces no direct runtime, provider or P6 authority.

## 13. E3 Delivery SHA-256 Inventory

> `THIS_E3_DELIVERY` records the exact E3 candidate files. The manifest does not hash itself, temporary test environments, DSN files, disposable database material or user REVIEW_REQUIRED files.

| SHA-256 | Path | Inventory treatment |
| --- | --- | --- |
| `0a28a699d9f84ab22b4913b905be91a708a484e406057cc789589aaa6170f18c` | `docs/E3_PROPOSAL_MASTER_PLAN_RECON_REPORT.md` | `THIS_E3_DELIVERY` |
| `42d45a1bfa95cec7b8404dcc1be89742116adb6c56749f582ef2c1b61a12dae2` | `docs/E3_PROPOSAL_MASTER_PLAN_DESIGN.md` | `THIS_E3_DELIVERY` |
| `08d82df6c06802c0403236638f007edee6f0e3f5bb76ddf50d36301b60ffde05` | `docs/E3_PROPOSAL_MASTER_PLAN_IMPLEMENTATION.md` | `THIS_E3_DELIVERY` |
| `c7cd5eb58d8d2e1670d1a460782568f350498d74c87ab93fe6297cf9840670f3` | `docs/E3_PROPOSAL_MASTER_PLAN_DELIVERY_REPORT.md` | `THIS_E3_DELIVERY` |
| `1ab01a10c0fea874de68afef1b4230692abb04048e8dcc701a1fc926d6605aaa` | `frontend/src/App.tsx` | `THIS_E3_DELIVERY` |
| `793c5c277e12ed6ea91ca1743b08fd0b5b6b4a342f36369535d20a07d7a14355` | `frontend/src/models.ts` | `THIS_E3_DELIVERY` |
| `530afeca26fc55e4d2041bbf4b68de3fb22a008bc1468fd80a6bd8ede070ebf3` | `frontend/src/api/adapters.ts` | `THIS_E3_DELIVERY` |
| `5b232fc3e607d3db6563fe89eb57f2a8337a49395328bde13035564b03cbd2ac` | `frontend/src/api/fixtureAdapters.ts` | `THIS_E3_DELIVERY` |
| `cd73ec4ac5f99fa8ebec6d2beb3263cb10657140d7b03de25018ca1968eb877b` | `frontend/src/api/productApiAdapters.ts` | `THIS_E3_DELIVERY` |
| `6ae0cf8b9f7a1855470760478c452ccebde7a51742a241d610e8852f3f8e6fd1` | `frontend/src/api/e3ProductApiAdapters.test.ts` | `THIS_E3_DELIVERY` |
| `fa5896272f2a862d9756d6c2daa48a396c0954257c414b2461b7727d033da950` | `hermes-runtime/migrations/0029_e3_proposal_master_plan.sql` | `THIS_E3_DELIVERY` |
| `545695a334457741ec91421f9a7370eb59c5acf6fb32f227f4057a7a87d19c4e` | `hermes-runtime/src/hermes_runtime/domain/entry_proposal_master_plan.py` | `THIS_E3_DELIVERY` |
| `83590b3c54743b7491402c23354ae1f874ff02ba7119271fc315fe9c3c1a4ba8` | `hermes-runtime/src/hermes_runtime/application/entry_proposal_master_plan_api.py` | `THIS_E3_DELIVERY` |
| `cf362dbd3116736e2810c0c50833769ca239934439bc1fc604561d99222f11af` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_proposal_master_plan.py` | `THIS_E3_DELIVERY` |
| `9e928cf5e5336bf0d028a019907ed1edbd3656e88d61cb6e34f59f3b4cab0e30` | `hermes-runtime/src/hermes_runtime/api_main.py` | `SUPERSEDED_BY_E4_COMPOSITION` |
| `437cc867291327211b480885dcbbcf0b593f210866e5be81b1dc247431209884` | `hermes-runtime/src/hermes_runtime/application/product_api.py` | `THIS_E3_DELIVERY` |
| `adeef3e99edbde689d6129bc14b59eef1c19c6ff033ca362eb18d17516dcbe79` | `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | `THIS_E3_DELIVERY` |
| `976ff8808ef181aba0fabc2887b4591bdd6e1a6092db76777f8f382805c51982` | `hermes-runtime/tests/test_e3_proposal_master_plan_domain.py` | `THIS_E3_DELIVERY` |
| `01c81430ddeaafe7f85bc80be7a74e0cb1a87859d04562bbc07e0e53e44a4f48` | `hermes-runtime/tests/test_e3_proposal_master_plan_fastapi.py` | `THIS_E3_DELIVERY` |
| `22fd45ae9e887d9351e1b42a3207e840d7f29e17da6c1c280a2a0ccedb307407` | `hermes-runtime/tests/test_e3_proposal_master_plan_product_api.py` | `THIS_E3_DELIVERY` |
| `466cfae61bc50caabdf34fa777ddde92938042c3380de29129ff08969abb21b5` | `hermes-runtime/tests/test_e3_proposal_master_plan_postgres.py` | `THIS_E3_DELIVERY` |


## 14. E4 Delivery SHA-256 Inventory
> `THIS_E4_DELIVERY` records the exact E4 closure files. The manifest does not hash itself, temporary test environments, DSN files, disposable database material or user REVIEW_REQUIRED files.
| SHA-256 | Path | Inventory treatment |
| --- | --- | --- |
| `44b418fbab5ca3693dd2532d6f04db472f2c5bfb198ece4574f38b90075ea7da` | `docs/E4_APPROVAL_BRIDGE_DELIVERY_REPORT.md` | `THIS_E4_DELIVERY` |
| `e4b956f250162b03c0a99e9ef7b74e25097d2f994567bd31d97d7f03064910ff` | `docs/E4_APPROVAL_BRIDGE_DESIGN.md` | `THIS_E4_DELIVERY` |
| `08b500e8d1b29a2ae9b29114a44fcd14f2e6730a0980fd515663ae6a4c7cffbc` | `docs/E4_APPROVAL_BRIDGE_IMPLEMENTATION.md` | `THIS_E4_DELIVERY` |
| `a15a0fffb7c3a35bc249ca9401c75ce3a6a9450b87ccce1f8edeee7f83281bf1` | `docs/E4_APPROVAL_BRIDGE_RECON_REPORT.md` | `THIS_E4_DELIVERY` |
| `1ab01a10c0fea874de68afef1b4230692abb04048e8dcc701a1fc926d6605aaa` | `frontend/src/App.tsx` | `THIS_E4_DELIVERY` |
| `cd73ec4ac5f99fa8ebec6d2beb3263cb10657140d7b03de25018ca1968eb877b` | `frontend/src/api/productApiAdapters.ts` | `THIS_E4_DELIVERY` |
| `793c5c277e12ed6ea91ca1743b08fd0b5b6b4a342f36369535d20a07d7a14355` | `frontend/src/models.ts` | `THIS_E4_DELIVERY` |
| `473c71eadb1d1a2ad7a062d8e1d2b5add646a75f3e3cb5a164a62bc93992668f` | `hermes-runtime/migrations/0030_e4_approval_bridge.sql` | `THIS_E4_DELIVERY` |
| `9e928cf5e5336bf0d028a019907ed1edbd3656e88d61cb6e34f59f3b4cab0e30` | `hermes-runtime/src/hermes_runtime/api_main.py` | `THIS_E4_DELIVERY` |
| `ebdb1d2904b2d93a90ffbd86c521f490bc5db39d9db0e5b97774d52d3c465aab` | `hermes-runtime/src/hermes_runtime/application/durable_approval_bridge_orchestrator.py` | `THIS_E4_DELIVERY` |
| `2b47387f85e797c4d05fe8b53be683908159003c08e9c8bfb5cf46411e1abeb2` | `hermes-runtime/src/hermes_runtime/application/entry_approval_bridge.py` | `THIS_E4_DELIVERY` |
| `91e68c9dba4e61f53a4294a94e1a3319245b00414454c4eede29ee566b856256` | `hermes-runtime/src/hermes_runtime/application/entry_approval_bridge_saga.py` | `THIS_E4_DELIVERY` |
| `437cc867291327211b480885dcbbcf0b593f210866e5be81b1dc247431209884` | `hermes-runtime/src/hermes_runtime/application/product_api.py` | `THIS_E4_DELIVERY` |
| `388448255b6d26f5590ad134ee2af6249847d24ed7afd7f57db20809ab285b86` | `hermes-runtime/src/hermes_runtime/domain/entry_approval_bridge.py` | `THIS_E4_DELIVERY` |
| `adeef3e99edbde689d6129bc14b59eef1c19c6ff033ca362eb18d17516dcbe79` | `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | `THIS_E4_DELIVERY` |
| `ee31ea37f5c8a341da9af56ee31967ef7f00a2e181cb4a210ceab340a664d341` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_entry_approval_bridge.py` | `THIS_E4_DELIVERY` |
| `5a65822d7141af709742d362225d3ef1ac89c1adfdc1defc7b6f8a925826c70c` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_project.py` | `THIS_E4_DELIVERY` |
| `01c81430ddeaafe7f85bc80be7a74e0cb1a87859d04562bbc07e0e53e44a4f48` | `hermes-runtime/tests/test_e3_proposal_master_plan_fastapi.py` | `THIS_E4_DELIVERY` |
| `eabd49e39995faf61cfa0614cf1e866ae33e4fa7f0c520d24a333a32da947fdf` | `hermes-runtime/tests/test_e4_approval_bridge_domain.py` | `THIS_E4_DELIVERY` |
| `3e10f003b5d2e27b7f82026e46a6e7a1a500a512e04486e074035362571e33d0` | `hermes-runtime/tests/test_e4_approval_bridge_fastapi.py` | `THIS_E4_DELIVERY` |
| `02182ef98878e52a74d3fa7b3017751c88b73517351d67d205f21b743a11984e` | `hermes-runtime/tests/test_e4_approval_bridge_postgres.py` | `THIS_E4_DELIVERY` |
| `7b9b849773843a2eae748b5f948d24383c6cf9e48d9d613a3fd8c0d5ccaf5d92` | `hermes-runtime/tests/test_e4_approval_bridge_product_api.py` | `THIS_E4_DELIVERY` |
| `0a2dd0eac0d6fce62a3ad076229fed601a8cc858479e5a9ad394e7f1b82df85c` | `hermes-runtime/tests/test_e4_approval_bridge_saga.py` | `THIS_E4_DELIVERY` |


## 15. E5–E7 Product Experience Closure
> This closure extends the E4 durable baseline without changing migrations 0001–0030 or any existing authority semantics.

| Phase / gate | Result |
| --- | --- |
| E4 Durable Approval Bridge | PASS — inherited remote master baseline. |
| E5 Product API / source-derived read model | PASS — 48 focused tests and real PostgreSQL source projection. |
| E6 Factory Home / resume | PASS — production real-API default, DEV-only demo fixtures, 40 frontend tests, build and lint. |
| E7 Live Production projection | PASS — source-derived snapshot/live-feed, real PostgreSQL evidence, Product API/FastAPI contracts, 40 frontend tests. |
| Fresh migration | PASS — 0001→0030 independent PostgreSQL 16 verification. |
| P6 Golden Todo / autonomous trial | PASS — 14 tests in task-only disposable PostgreSQL. |
| Full Runtime | PASS — 702 run, 12 skipped, 0 failures in 370.956 seconds (Stage A P6 secret guard repair). |
| P0–P5 no-DB discovery | PASS — 699 run, 432 skipped, 0 failures. |
| Frontend production quality | PASS — 40 tests, production build, oxlint 0 warnings / 0 errors. |

### E5 Delivery SHA-256 Inventory
| SHA-256 | Path | Inventory treatment |
| --- | --- |
| `e9b322215e60984212f918375ab58c13de010cd29249734b4ba07a31ea2acb24` | `docs/E5_PRODUCT_API_READ_MODEL_DELIVERY_REPORT.md` | `THIS_E5_DELIVERY` |
| `38dd53b93a9dd1e9adbbb72a8a4ff14947d293442a882b71be7c2dbb1a545297` | `docs/E5_PRODUCT_API_READ_MODEL_DESIGN.md` | `THIS_E5_DELIVERY` |
| `9e928cf5e5336bf0d028a019907ed1edbd3656e88d61cb6e34f59f3b4cab0e30` | `hermes-runtime/src/hermes_runtime/api_main.py` | `THIS_E5_DELIVERY` |
| `440bef63b2d74cff73b5f82e76b574b1effd152bd05dd8e5da96602cd14478eb` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_factory_home_read_model.py` | `THIS_E5_DELIVERY` |
| `568739c3a7a27d830c45ac2f6695eecc66501c7b3ff960719c435c42c046070d` | `hermes-runtime/tests/test_e5_product_read_model_postgres.py` | `THIS_E5_DELIVERY` |
| `855df2838b325d83297a5b94af2fa8ad4eb8f8e6abb69e4b40834f0714b62490` | `hermes-runtime/tests/test_factory_home_read_model.py` | `THIS_E5_DELIVERY` |

### E6 Delivery SHA-256 Inventory
| SHA-256 | Path | Inventory treatment |
| --- | --- |
| `9751256b07d7b8d4e3baefcaa933f991655bdc8d7ed3dbbdd9b5938efdd5e033` | `docs/E6_FACTORY_HOME_RESUME_DELIVERY_REPORT.md` | `THIS_E6_DELIVERY` |
| `4394ca12de5bfcc156953c1fbf86f5a2911f772a0e4a6a86cf48cea90e29033b` | `docs/E6_FACTORY_HOME_RESUME_DESIGN.md` | `THIS_E6_DELIVERY` |
| `1ab01a10c0fea874de68afef1b4230692abb04048e8dcc701a1fc926d6605aaa` | `frontend/src/App.tsx` | `THIS_E6_DELIVERY` |
| `9788864a7ae3ea8f1f15463514ba2545018fb67b687cf3d4a2afcab1a3441564` | `frontend/src/api/index.ts` | `THIS_E6_DELIVERY` |
| `dbe6271a8fab806a32292ecc566994b5782d551bda4f3f750fc9a7c6ae0d7272` | `frontend/src/contract.test.ts` | `THIS_E6_DELIVERY` |

### E7 Delivery SHA-256 Inventory
| SHA-256 | Path | Inventory treatment |
| --- | --- |
| `7c044c37b784ee857dd1c4cca9b29eab6635d156d6e33d66f1209ca268ae795d` | `docs/E7_LIVE_PRODUCTION_PROJECTION_DELIVERY_REPORT.md` | `THIS_E7_DELIVERY` |
| `aea6b11dbdde8b90748d2563e8accdd38a7ae9444b184e86b4c1c832f4e18054` | `docs/E7_LIVE_PRODUCTION_PROJECTION_DESIGN.md` | `THIS_E7_DELIVERY` |
| `1ab01a10c0fea874de68afef1b4230692abb04048e8dcc701a1fc926d6605aaa` | `frontend/src/App.tsx` | `THIS_E7_DELIVERY` |
| `530afeca26fc55e4d2041bbf4b68de3fb22a008bc1468fd80a6bd8ede070ebf3` | `frontend/src/api/adapters.ts` | `THIS_E7_DELIVERY` |
| `5b232fc3e607d3db6563fe89eb57f2a8337a49395328bde13035564b03cbd2ac` | `frontend/src/api/fixtureAdapters.ts` | `THIS_E7_DELIVERY` |
| `4e64d28ef8c6428c6e239f0f8132d216cd1ee723ef01928244eedced95ff56d4` | `frontend/src/api/productApiAdapters.test.ts` | `THIS_E7_DELIVERY` |
| `cd73ec4ac5f99fa8ebec6d2beb3263cb10657140d7b03de25018ca1968eb877b` | `frontend/src/api/productApiAdapters.ts` | `THIS_E7_DELIVERY` |
| `dbe6271a8fab806a32292ecc566994b5782d551bda4f3f750fc9a7c6ae0d7272` | `frontend/src/contract.test.ts` | `THIS_E7_DELIVERY` |
| `793c5c277e12ed6ea91ca1743b08fd0b5b6b4a342f36369535d20a07d7a14355` | `frontend/src/models.ts` | `THIS_E7_DELIVERY` |
| `9e928cf5e5336bf0d028a019907ed1edbd3656e88d61cb6e34f59f3b4cab0e30` | `hermes-runtime/src/hermes_runtime/api_main.py` | `THIS_E7_DELIVERY` |
| `437cc867291327211b480885dcbbcf0b593f210866e5be81b1dc247431209884` | `hermes-runtime/src/hermes_runtime/application/product_api.py` | `THIS_E7_DELIVERY` |
| `adeef3e99edbde689d6129bc14b59eef1c19c6ff033ca362eb18d17516dcbe79` | `hermes-runtime/src/hermes_runtime/infrastructure/fastapi_app.py` | `THIS_E7_DELIVERY` |
| `16c17f8164167e050152502fe6e10876f253cd10396098ab6a5df7f4ae3f345a` | `hermes-runtime/src/hermes_runtime/infrastructure/postgres_live_production_read_model.py` | `THIS_E7_DELIVERY` |
| `0b9eea74d2fc4a66fbfb84a430d30bfc9974d75b3bdb472e228714d8e999c2de` | `hermes-runtime/tests/test_e7_live_fastapi.py` | `THIS_E7_DELIVERY` |
| `43bc8b1b908a5a00036d6f26720fefc036ff4e7e827dbc17ee815f8a9ab3d13b` | `hermes-runtime/tests/test_e7_live_product_api.py` | `THIS_E7_DELIVERY` |
| `a2c09a9a3fd416edd77528c4201bdd6076fe4cffecaf10e00e95e7658db3e549` | `hermes-runtime/tests/test_e7_live_production_postgres.py` | `THIS_E7_DELIVERY` |

### Stage A P6 Secret Guard Repair SHA-256 Inventory
| SHA-256 | Path | Inventory treatment |
| --- | --- | --- |
| `df32a9885c58d1e5b00ab3054a104fb212c2780ee9a6d8a529ffcbfc68428e49` | `hermes-runtime/migrations/0031_p6_secret_guard_structured_jsonb.sql` | `THIS_P6_SECRET_GUARD_REPAIR` |
| `c253ad76a3db19134019895001a2f2634f67eec46ba6b0621a59d2eba5e17ca1` | `hermes-runtime/tests/test_execution_postgres.py` | `THIS_P6_SECRET_GUARD_REPAIR` |
| `ebb12079042348873239aaf07f18856299fa92e2de851a47d46e225b0ae9212c` | `docs/P6_SECRET_GUARD_FALSE_POSITIVE_POLICY_REPAIR_DESIGN.md` | `THIS_P6_SECRET_GUARD_REPAIR` |
| `fb682085932006da616ae15acc736aad056987710407f5504b1def7e604cf785` | `docs/P6_SECRET_GUARD_FALSE_POSITIVE_POLICY_REPAIR_DELIVERY_REPORT.md` | `THIS_P6_SECRET_GUARD_REPAIR` |

Stage A adds only forward migration `0031` and structured P6 secret-guard evidence. It preserves E4 durable identity, all prior authority semantics, and the E8 NOT ENTERED boundary. Real PostgreSQL evidence: focused guard/admission 3/3 PASS; P6 Execution/permissions/recovery plus E4 durable 47/47 PASS; P6 standalone 14/14 PASS; Full Runtime 702 run, 12 skipped, 0 failures in 370.956 seconds; frontend 40 PASS, build PASS, lint 0 warnings / 0 errors.

## 16. Stage A2 Execution-Prepare Convergence SHA-256 Inventory

> `THIS_P6_SECRET_GUARD_STAGE_A2` records the forward-only convergence delivery. The manifest remains non-self-referential and does not hash temporary test environments, DSNs, disposable databases, E8 forensic worktrees or `REVIEW_REQUIRED` files.

| SHA-256 | Path | Inventory treatment |
| --- | --- | --- |
| `ba990e1a1029673dffdc8f7cc020bf3ce1034a84b4d1dcfe19f3bd95800f107f` | `hermes-runtime/migrations/0032_p6_execution_prepare_structured_secret_guard.sql` | `THIS_P6_SECRET_GUARD_STAGE_A2` |
| `c253ad76a3db19134019895001a2f2634f67eec46ba6b0621a59d2eba5e17ca1` | `hermes-runtime/tests/test_execution_postgres.py` | `THIS_P6_SECRET_GUARD_STAGE_A2` — replaces its prior Stage A hash because the file is modified by this stage. |
| `67f74458aa5eafcf3265a1ca104977900d36c7dab65e4f960e9f568e395f0313` | `docs/P6_SECRET_GUARD_STAGE_A2_DESIGN.md` | `THIS_P6_SECRET_GUARD_STAGE_A2` |
| `cd04c271d434c342d3bc5dc40ac45b1402ad74eb19838986c8565ec08b190b33` | `docs/P6_SECRET_GUARD_STAGE_A2_DELIVERY_REPORT.md` | `THIS_P6_SECRET_GUARD_STAGE_A2` |

Stage A2 changes no historical migration, E4 durable identity, P6 authority state machine, business schema, role or grant. Fresh PostgreSQL evidence confirms owner `hermes_execution_owner`, `SECURITY DEFINER`, hardened `pg_catalog` search path, unchanged ACL, no legacy sandbox text-regex callsite, canonical helper use, and the current action-route set. Local gates: P6 bootstrap/autonomous `14/14 PASS`; no-DB `704 run / 437 skipped / 0 failures`; Full Runtime `704 run / 12 skipped / 0 failures`; frontend `40/40 PASS`, build PASS and oxlint `0/0`. At the Stage A2 closure point, E8 was **NOT ENTERED**; PR #24 has since merged and its master verification completed before this independent E8 continuation.

## 17. E8 Production Entry Trial SHA-256 Inventory

> `THIS_E8_COMPLETION` records only the minimum cross-phase integration contract. The manifest remains non-self-referential and excludes temporary virtual environments, disposable databases, DSNs, test logs, Stage A2 worktrees and any E9 work.

| SHA-256 | Path | Inventory treatment |
| --- | --- | --- |
| `91e68c9dba4e61f53a4294a94e1a3319245b00414454c4eede29ee566b856256` | `hermes-runtime/src/hermes_runtime/application/entry_approval_bridge_saga.py` | `THIS_E8_COMPLETION` — command type alignment for the existing E4 GraphPatch port. |
| `437cc867291327211b480885dcbbcf0b593f210866e5be81b1dc247431209884` | `hermes-runtime/src/hermes_runtime/application/product_api.py` | `THIS_E8_COMPLETION` — safe ApprovalPreview DTO, without frozen blueprint disclosure. |
| `69f29448614012d3a8775f890fe7453bc74d964e94ccb8274ae50a7b926534a4` | `hermes-runtime/src/hermes_runtime/trial/driver.py` | `THIS_E8_COMPLETION` — P6 existing-entry continuation adapter and read-only stage observer. |
| `505b54450180297aa56c1522e15e299af61d78a68563e909645cf64d4c821e6b` | `hermes-runtime/tests/test_e8_production_entry_trial.py` | `THIS_E8_COMPLETION` — fresh PostgreSQL same-project vertical acceptance. |
| `e9380e406c12d27fd82fb9f6a51771264861052d23241d396800b06f8405ec3a` | `docs/E8_PRODUCTION_ENTRY_TRIAL_DESIGN.md` | `THIS_E8_COMPLETION` |
| `e08891aa8fd0e228d0774f27938362bb45dbe68ff46cbfe8eebded7afe6b7a63` | `docs/E8_PRODUCTION_ENTRY_TRIAL_DELIVERY_REPORT.md` | `THIS_E8_COMPLETION` |

E8 preserves migrations `0001–0032`, E4 durable identity, the P6 authority state machine, schema, roles and grants. The old forensic secret preflight is absent; 0031/0032 remain the only secret-policy authority. The final local gates are E8 vertical `1/1 PASS`; no-DB `705 run / 438 skipped / 0 failures`; Full Runtime `705 run / 12 skipped / 0 failures`; frontend `40/40 PASS`, build PASS and oxlint `0/0`. E8 is complete and **does not enter E9**.

