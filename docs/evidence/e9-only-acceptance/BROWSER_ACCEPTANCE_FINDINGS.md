# E9-only Browser Acceptance Findings

## Home / default presentation

- Production static build rendered at `http://localhost:4174/home` after the BrowserRouter entry correction.
- The browser displayed the skip link, brand, workspace navigation, Product API status strip, Display settings button, Home heading, and New production entry.
- With no authenticated Product API session, Home displayed the explicit localized `Request unavailable` state and retry affordance; it did not render invented projects, execution state, or fabricated progress.
- The default visual state was light, with a responsive workspace shell, semantic status marker, focusable navigation, and readable error card.

## Evidence boundary

This browser run used only the E9-only production static build and unavailable local Product API state. No provider, OIDC token, production system, authority command, Gate decision, E11 command, or persistent business data was contacted or mutated.

## Arabic RTL check

- Selecting `ar-SA` updated the document title and direction to Arabic/RTL. Sidebar and settings panel moved to the expected RTL layout, and Arabic labels including Home, Drafts, Gate inbox, Display settings, Theme, Language, Density, and Retry rendered.
- Technical Product API status content remained LTR-isolated as intended.
- **Defect found:** multiple visible product strings remained English in Arabic, including `Projects`, `New production`, the Home detail, the unavailable-state title/description, and several preference option labels. This is a real acceptance gap: catalog structural completeness alone is insufficient. The E9 closure must not claim complete localization until visible presentation strings are translated for every supported locale.

## Arabic RTL recheck after complete catalog integration

The rebuilt production application was reopened with the persisted `ar-SA` preference. The browser showed Arabic copy for the skip link, navigation, primary action, Product API status strip, Home heading and description, unavailable-state title/description, and retry action. The retained `Product API` wording is a technical product identifier rather than a fallback UI phrase. RTL positioning remained correct and source-derived unavailable state remained explicit, with no invented operational facts.

## RTL + high-contrast-dark combination

With Arabic still selected, choosing `high-contrast-dark` immediately applied the high-contrast black canvas, white text, yellow primary action, visible dotted boundaries, and clear form-control outlines. The RTL sidebar, settings panel, error state, and interactive controls remained readable and operable together; this validated a non-default locale/theme combination rather than only isolated preferences.

## Simplified Chinese + CJK font + high-contrast-dark combination

The production build rendered complete Simplified Chinese navigation, headings, preference labels, unavailable state, and retry action after selecting `zh-CN`. Selecting the CJK UI font preserved clear Chinese glyphs, readable spacing, and functional controls under the high-contrast-dark theme. No clipping, overlapping controls, or ordinary English fallback was observed in the viewport.

## Responsive viewport screenshots

The 320 px production screenshot showed a compact mobile presentation: branding and Home control remained visible, the main content stayed within the viewport, the primary action and explicit unavailable state remained readable, and no fabricated data appeared. The 768 px screenshot retained the workspace navigation and full-width unavailable-state card with readable control sizing. Both screenshots reveal intentional horizontal navigation overflow with a visible scroll affordance rather than clipping; the main content itself did not horizontally overflow.

At 1024 px, the desktop sidebar, status strip, heading/action row, and full-width unavailable-state card were all visible with no overlap or clipping. Together with the 320 px and 768 px screenshots, this completes the responsive visual evidence matrix for the E9-only production build.
