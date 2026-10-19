# Design brief: Group Insurance Desk (staff web app)

- **Status:** Decided by the product owner (2026-10-19) unless marked otherwise. Input for the ui-designer (`docs/design/design-system.md`) and the ux-designer (`docs/design/ux/`).

## Users and setting
Bank branch employees selling group insurance many times a day, on bank desktop browsers (versions open, Q17), often keyboard-first, sometimes on slow networks. Also checkers, operations and auditors. A mobile app comes later and reuses the API, not these screens.

## Character
Minimal, calm, very professional, fast. Plain screens with generous white space, compact data tables, one main action per screen, nothing decorative. It should feel trustworthy for money and policy work.

## Inspiration: borrow patterns, never branding
| Source | Borrow | Leave out |
|---|---|---|
| GOV.UK Design System (main reference) | Form and wizard patterns: one question group per step, error summary linked to fields, plain wording, accessibility, speed | – |
| Razorpay and Stripe dashboards | Tables, filters, status badges, detail pages with a timeline, calm professional look | Heavy analytics charts |
| PhonePe | Clear payment and policy status screens (success, failed, pending, needs attention) with the next step spelled out | Consumer styling, promotions (more relevant to the later mobile app) |
| PolicyBazaar | Plan comparison cards, for the plan step only | Banners, marketing, crowded layouts |
| Zopper partner portals | Partner sale-flow ideas | Sales-style visuals |
No logos, brand colours, copy or assets from any real company. The product name is the brand-neutral "Group Insurance Desk".

## Performance budget (checked in CI once the ui-designer fixes the numbers)
| Item | Target |
|---|---|
| Fonts | System font stack only, no web fonts |
| Graphics | No images, illustrations or gradients; inline SVG icons only |
| Motion | Under 150 ms, off when the user prefers reduced motion |
| First-load JavaScript | At most 150 KB gzipped (Proposed) |
| Routes | Each screen loaded on demand |
| Stability | No layout shift on load; skeletons instead of spinners for tables |

## Accessibility
WCAG 2.2 AA: contrast at least 4.5:1, visible focus, full keyboard use, labels and error messages tied to fields.

## Constraints
React + Tailwind CSS v4 + inline SVG (ADR-0001, Amendments 1 and 2); no new dependencies. Business rules stay on the server: buttons come from `allowed_actions`, amounts are shown exactly as the API returns them.
