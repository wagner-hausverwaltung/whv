# ADR-0005: Portal UI stack — Material UI + i18n with browser detection

- Date: 2026-05-24
- Status: Accepted
- Resolves: REQUIREMENTS.md §5 (Web stack)
- Supersedes: implicit Tailwind + shadcn/ui pick from REQUIREMENTS.md "Stack at a glance"

## Context

The first portal iteration shipped on **Tailwind CSS + shadcn/ui**, per REQUIREMENTS.md "Stack at a glance". This worked for the early flows (login, property list, tickets, resolutions). Two real-world needs surfaced once a second customer touched the portal:

1. The **admin UI** (Verwalter) is server-rendered Jinja + Pico.css + HTMX. The two surfaces feel like different products — different palettes, different form widgets, different spacing. With both eventually being touched by the same Verwalter (admin) and the same Eigentümer (portal), the visual disconnect is jarring.
2. The portal needs **dark mode + system-preference detection** and **EN/DE i18n with browser-language default**. Both are doable with Tailwind, but require building primitives we'd otherwise get for free from a component library.

## Decision

**Adopt Material UI (`@mui/material`) as the portal's component library**, replacing Tailwind + shadcn/ui.

- Theming: a single `ThemeProvider` exposes the WHV palette (`#1863DC` primary, `#212121` text, etc.) in both light and dark modes. System mode follows `prefers-color-scheme`; the user can override via a header toggle persisted to `localStorage`.
- Typography: keep **Montserrat (display)** + **Noto Sans (body)** as currently loaded from Google Fonts; pass them into the MUI theme's `typography.fontFamily`.
- Icons: `@mui/icons-material` for the standard set. The ticket category Font Awesome icons (from the casavi-equivalent taxonomy) are kept as a separate small icon font load, since MUI doesn't have 1:1 equivalents for some of the German-property-management-specific iconography.
- The admin UI is migrated from Jinja → a React + MUI SPA in a follow-up effort (Phase 4c). Until that lands, the Jinja admin keeps its current Pico.css styling. The migration unifies both surfaces.

For i18n: **`i18next` + `react-i18next` + `i18next-browser-languagedetector`**.

- Default locale = browser language (`navigator.language`), fallback `de`.
- Manual override via a flag dropdown in the header, persisted to `localStorage` (key `i18nextLng`, the library's default).
- Translation files: `web/src/i18n/locales/{de,en}.json`, one flat namespace to start. If the file grows past ~500 keys we'll split per-feature.
- Backend strings (email subjects, German enum values surfaced to API consumers) stay German-only for v1. Adding backend i18n means adding a per-user `language` column + accepting `Accept-Language`; deferred until the portal language audit shows it's actually needed (most users are German-speaking).

## Why Material UI over alternatives

- **Component completeness** — Autocomplete, DataGrid, DateTimePicker, grouped Select, Snackbar all ship out-of-the-box. shadcn/ui is mostly Radix primitives that still need composition; MUI covers more surface area per component.
- **Theming primitives** — built-in light/dark switching, palette overrides, dense mode. Tailwind needs hand-rolled CSS variables for this.
- **Accessibility** — MUI's components ship with sensible ARIA out of the box. shadcn inherits Radix's accessibility (also good), but the broader MUI surface means fewer custom-built widgets where we have to remember the rules ourselves.
- **Admin-UI parity** — the upcoming admin SPA is going to want a `DataGrid` for queues anyway. Picking MUI here means we don't run two component libraries.

Trade-offs:

- **Bundle size** — MUI adds ~140 KB gzipped to the portal bundle. Acceptable for an internal-ish customer portal; we'll lazy-load detail pages once the bundle exceeds 500 KB.
- **CSS-in-JS at runtime** — Emotion-based MUI compiles styles in the browser. Slower than Tailwind's purged CSS. Mitigation: most pages are simple and the perf hit is invisible on the modern devices our users actually use (no IE-equivalent constraints).
- **Deviation from REQUIREMENTS.md** — this ADR exists precisely to document that.

## Why not …

- **Keep Tailwind + shadcn** and just restyle admin to match: would work but doesn't address the dark-mode/i18n primitives gap. Also, the admin Jinja templates need replacing anyway (HTMX-only flows are awkward for the Verwalter's eventually-expected richer interactions like drag-and-drop document upload).
- **Mantine** or **Chakra**: comparable to MUI on the basics; MUI has the strongest DataGrid story for the admin SPA.
- **Headless UI + custom CSS**: more work for less polish at our team size.

## Consequences

- All portal pages get ported from Tailwind classes to MUI components. ~13 pages, done in stages over multiple commits.
- `tailwindcss`, `postcss`, `autoprefixer`, and the `tailwind.config.js` go away once every page is ported. (Kept temporarily during the migration so unported pages still work.)
- The custom `@layer components` rules (`.card`, `.btn-primary`, `.flash-error`, `.muted`) are deleted as their consumers migrate.
- New deps: `@mui/material`, `@mui/icons-material`, `@emotion/react`, `@emotion/styled`, `i18next`, `react-i18next`, `i18next-browser-languagedetector`. All MIT-licensed.
- The admin React SPA (Phase 4c) inherits the same theme + i18n setup.

## Revisit triggers

- If bundle gzip > 500 KB on a single page and lazy-loading doesn't bring it back under, evaluate dropping MUI for a lighter alternative.
- If a third party (e.g. a Beirat-only portal variant for a different WEG) needs to skin the portal differently, MUI's theming should cover it; if not, revisit.
