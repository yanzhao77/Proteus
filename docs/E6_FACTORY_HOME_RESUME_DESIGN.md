# E6 Factory Home and Resume Design

## Product boundary

Factory Home is a **source-derived navigation and resume surface**. It does not invent a Production state, submit Project lifecycle commands, invoke a Worker, manage a Scheduler, start an Execution, decide a Gate, or transform a browser interaction into authority. The browser owns only transient form and rendering state; server facts remain the source of truth.

## Adapter policy

| Build context | Adapter policy |
| --- | --- |
| Production | `productApiAdapters()` is the only supported adapter. |
| Development demo | Fixture adapters may be selected only when both `import.meta.env.DEV` and `VITE_PROTEUS_DEMO === "true"` are true. |
| Runtime controls | No user-visible runtime switch exists for fixture data, authority pending mode, workers, scheduler, execution, verification, evidence, recovery, or provider configuration. |

The former browser flag that could select an authority placeholder is intentionally removed. A production bundle cannot silently substitute fixture or placeholder data for the Product API.

## Resume behavior

Entry Draft creation sends the existing E1 command with one locally retained idempotency key. The key is generated once when first submitted. If the browser receives an unknown/unavailable result, a retry reuses **the same key** and preserves the same semantic request. Only a Product API `data` result, which represents the authority response, clears the pending key and navigates to the authoritative Draft route.

The user sees explicit `RECEIPT PENDING — DRAFT NOT YET APPLIED` and `OUTCOME UNKNOWN — RETRY REUSES THE SAME KEY` states. No local Draft card, Project, Production, or progress value is created after an uncertain result.

Draft and Production routes resolve their IDs from the URL and obtain the view from the current adapter. Reload therefore re-fetches server-backed data rather than relying on memory or local storage. Pending/error/empty states remain visibly distinct; loading uses skeletons and no source-backed Portfolio is never represented as an empty success state.

## Accessibility and visual contract

The existing console/JARVIS visual system retains semantic labels, status icons and non-color-only status treatment. Existing contrast, reduced-motion and responsive theme contracts remain part of the focused suite. Gate and Production cards remain navigational links; no direct semantic mutation control is added.
