# E9–E11 Global Product Workspace Acceptance Closure — E9-only Design

**Status:** E9 acceptance closure final — E11 remains PARTIAL / ACCEPTANCE GAP
**Closure base:** remote `master` `1cd0ceb9393a2b390f515cbfe741c998d3f1064d`
**Scope decision:** E9-only. E10 is regression-only. E11 remains **PARTIAL / ACCEPTANCE GAP**.

## 1. Decision and authority boundary

PR #26 delivered the initial global workspace, but its E9 acceptance scope only covered `en-US`, `zh-CN`, `system`, `light`, `dark`, and a narrow display control set. This closure completes the E9 presentation system without introducing migrations, backend preferences, Product API commands, or authority changes.

The closure must not use frontend state as authority. It must not add an E11 retry, reconcile, reverify, cancel, or recovery command. The existing public Project API exposes only read projections and reconciliation findings; public human-gate decisions are E12 scope. Consequently, every E11 current-status reference must read **PARTIAL / ACCEPTANCE GAP** until separately authorized authority work exists.

## 2. E9 implementation contract

The frontend will use a typed catalog keyed by all production display strings. The required supported locale set is:

`zh-CN`, `zh-TW`, `en-US`, `en-GB`, `ja-JP`, `ko-KR`, `fr-FR`, `de-DE`, `es-ES`, `it-IT`, `pt-BR`, `nl-NL`, `pl-PL`, `ru-RU`, `uk-UA`, `tr-TR`, `id-ID`, `vi-VN`, `th-TH`, `hi-IN`, `ar-SA`, and `he-IL`.

Every catalog must contain the same required key set. A missing, duplicate, or dead key is a test failure. `Intl` supplies locale-safe number, percent, date/time, relative time, duration, byte size, token count, plural, select, and ordinal formatting. Stable backend error codes remain LTR technical values; their title, description, and action use `error.<stable_code>.*` catalog keys. No component silently treats a missing translation as a PASS condition.

The supported themes are `system`, `light`, `dark`, `high-contrast-light`, `high-contrast-dark`, `protanopia-safe`, `deuteranopia-safe`, `tritanopia-safe`, `monochrome`, and `print`. Accent selection is constrained to non-semantic surface/action color only. Semantic status colors, authority state, and access boundaries do not change with accent or theme.

Display preferences are browser-only, non-sensitive, and versioned in local preference storage: locale, theme, accent, UI font family, monospace font family, font size, line height, density, and reduced motion. They never contain OIDC/session tokens, Product API identity, creator scope, or operational data. The document element owns `lang`, `dir`, `data-theme`, `data-accent`, `data-font-size`, `data-line-height`, and density attributes. RTL locales are `ar-SA` and `he-IL`; technical IDs, hashes, URLs, paths, receipts, codes, event cursors, and log blocks use LTR bidi isolation.

## 3. Page and component scope

All existing E9 routes use the same shell and catalog: `/home`, `/new`, `/drafts`, `/drafts/:id`, `/productions`, `/productions/:id`, `/productions/:id/operations`, and `/gates`. This includes headings, labels, table headers, tooltips, buttons, validation, loading, pending, empty, error, stale, unavailable, retry states, and screen-reader labels. It does not claim a future E12–E16 surface.

The accessibility contract requires a skip link, visible keyboard focus, correctly labelled settings control, focus return from the preferences panel, `aria-live` for resource-state transitions, semantic table labels, no-color-only statuses, and readable text/table equivalents of the existing DAG and event log. Responsive test widths are 360, 768, 1280, and 1440 CSS pixels, including 200% zoom / extra-large font behavior.

## 4. Acceptance matrix

Programmatic component/route coverage runs each of 22 locales and 10 themes at least once. Dedicated RTL tests cover Arabic and Hebrew direction, technical LTR isolation, and long mixed-script identifiers. CJK coverage uses `zh-CN`, `zh-TW`, `ja-JP`, and `ko-KR`; additional script coverage includes Thai and Hindi. Visual browser coverage covers light, dark, high-contrast, color-safe, print, CJK, RTL, compact/spacious, extra-large font, and the four responsive widths. The browser uses only a clean local checkout and unavailable/non-production API state; no real provider or production environment is contacted.

## 5. Migration and stop decision

**Migration decision: NO MIGRATION.** UI preferences are non-sensitive browser presentation preferences. No durable read model or semantic command requires a new database object. Any need for a Project operation command, durable UI preference table, control-plane impersonation, direct DML, E4 identity change, or P0–P6/E1–E8 authority change stops this closure for separate authorization.


## Final closure qualification

The E9-only implementation now satisfies this document's E9 acceptance contract: all 22 typed locale catalogs have a complete keyset; ten themes and non-sensitive display preferences are implemented; RTL/CJK, accessibility, and responsive production-browser evidence are recorded; and no core visible non-English string may equal its English fallback. The authoritative delivery evidence is `E9_ONLY_ACCEPTANCE_CLOSURE_DELIVERY_REPORT.md`.

E11 remains **PARTIAL / ACCEPTANCE GAP**. This document does not authorize or claim any user-callable recovery operation, command transport, Control Plane impersonation, or E12 decision capability.
