# E9-only Acceptance Closure Design

## Scope and authority boundary

This closure is deliberately limited to **E9 Global Design System acceptance**. It implements presentation, localization, display-preference, accessibility, and browser-verification capabilities only. It introduces no migration, schema change, role, grant, Product API mutation, Control Plane transport, OIDC scope expansion, provider configuration, or E11 authority command.

E11 remains **PARTIAL / ACCEPTANCE GAP**. The project-operations view remains a source-derived E7 projection with navigation to the existing Gate Inbox. It does not claim a user-callable retry, reconcile, reverify, cancel, or recovery acknowledgement command because no compliant OIDC-facing authority surface exists for those semantics.

## Localization contract

The typed E9 catalog contains a full, identical keyset for these 22 BCP 47 locales: `zh-CN`, `zh-TW`, `en-US`, `en-GB`, `ja-JP`, `ko-KR`, `fr-FR`, `de-DE`, `es-ES`, `it-IT`, `pt-BR`, `nl-NL`, `pl-PL`, `ru-RU`, `uk-UA`, `tr-TR`, `id-ID`, `vi-VN`, `th-TH`, `hi-IN`, `ar-SA`, and `he-IL`.

Static workspace labels, state labels, page descriptions, empty/error/action messages, preferences, and core shell navigation use the catalog. The catalog has no partial-pack fallback: every locale has the complete typed message keyset. A quality test additionally rejects an English fallback for core visible messages in every non-English locale. `ar-SA` and `he-IL` set `dir="rtl"`; IDs, API names, hashes, and other technical values remain directionally isolated.

## Presentation-preference contract

The persisted browser preference payload is versioned as `proteus.e9.preferences.v2` and stores only non-sensitive presentation choices: locale, theme, accent, UI/monospace font, font size, line height, density, and reduced-motion. It never stores an authorization header, bearer token, refresh token, API key, OIDC token, or provider credential. Startup applies the same presentation attributes before the React mount to avoid avoidable theme flash.

Themes are `system`, `light`, `dark`, `high-contrast-light`, `high-contrast-dark`, `protanopia-safe`, `deuteranopia-safe`, `tritanopia-safe`, `monochrome`, and `print`. Fonts use system/CJK/serif UI stacks and system/JetBrains-style monospace stacks; remote web-font loading is not introduced.

## Accessibility and visual contract

The shell provides a visible-on-focus skip link, keyboard focus states, a focusable main landmark, labelled icon controls, a modal preference surface, live state semantics, non-colour status markers, reduced-motion support, high-contrast tokens, print rules, and responsive navigation/content layout. Browser evidence covers Arabic RTL with high-contrast dark, Simplified Chinese with CJK font and high-contrast dark, and production screenshots at 320 px, 768 px, and 1024 px.

## Explicit exclusions

No E12 Gate Decision Center, E13 proposal/plan editor, E14 worker control plane, E15 provider configuration, E16 deployment center, or any second authority path is added by this closure.
