# Tap Design System

Canonical design tokens and patterns for all Tap surfaces. Any new surface starts here.
Surfaces: tappayment.io (Tap-Hub repo), the local dashboard (mcp-server/dashboard.js),
and future builder / TapWork views.

## Principle
Clean but information-rich. Professional, not flashy — this is a financial tool. Depth
comes from layered shadow and alignment, never from gradients-as-decoration or glow.
Motion only where it means something (a live indicator), never for ornament.

## Color

| Token       | Value     | Use |
|-------------|-----------|-----|
| ink         | `#1a1d29` | Primary text, dark fills |
| slate       | `#5b6473` | Secondary text, descriptions |
| mute        | `#8a92a1` | Labels, captions, tertiary |
| line        | `#e5e8ee` | Card borders, dividers |
| lineSoft    | `#eef0f4` | Internal dividers inside cards |
| panel       | `#f7f8fb` | Subtle panel fill |
| accent      | `#4338ca` | Primary indigo — buttons, links, key data |
| accentAlt   | `#6d63e0` | Secondary bar/series color |
| accentSoft  | `#eef0fd` | Indigo tint — pills, glyph backgrounds |
| ok          | `#0f9d75` | Settled, verified, fees earned |
| danger      | `#a32d2d` | High severity (bg `#fcebeb`) |
| white       | `#ffffff` | Card background |

## Elevation
- Card: `border: 1px solid line` + `border-radius: 16px`
- Card background: `linear-gradient(180deg,#fbfbfe 0%,#ffffff 60%)`
- Card shadow: `0 1px 2px rgba(26,29,41,.04), 0 8px 24px -12px rgba(67,56,202,.10)`
- Flat sub-cards (inside a card): no shadow, `lineSoft` borders only

## Radius
- Cards: 16 · Buttons/inputs: 9 · Small chips: 8 · Pills/dots: 999

## Spacing
Use 4/6/8/10/12/16/20/24/32. Card padding 22–24. Section gap 16. Stat cell padding 16–18.

## Type
| Role     | Size            | Weight | Notes |
|----------|-----------------|--------|-------|
| display  | clamp(34,5.5vw,54) | 800 | letter-spacing -1.2, hero only |
| h2       | clamp(24,3.5vw,32) | 750 | letter-spacing -.6 |
| cardTitle| 19              | 500–700| letter-spacing -.3 |
| stat     | 22–24           | 500–800| `font-variant-numeric: tabular-nums`, ls -.5 |
| body     | 15–17           | 400 | line-height 1.55–1.6 |
| small    | 13–13.5         | 400 | color slate |
| label    | 11–12           | 500–600| UPPERCASE, letter-spacing .4–.8, color mute |
| mono     | 11.5–13         | 400 | ui-monospace/Menlo — addresses, tx, code |

Font stack: `ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif`

## Component patterns

**Card** — bordered, 16 radius, gradient bg, shadow, 22–24 padding.

**Stat grid** — stats in equal columns divided by `1px solid lineSoft` verticals, each cell
a small UPPERCASE label above a tabular-nums number. Sits directly under the card header,
separated by a full-width `lineSoft` rule.

**Bar row** — label + value on one line, then a 4px `lineSoft` track with an `accent`
(or `accentAlt` for the second series) fill, radius 999. Used for per-agent breakdowns.

**Feed row** — left: 5px accent dot + bold-ish name + mono address; right: tabular value
+ accent link. Separated by `1px solid #f3f4f8`, last row no border.

**Live indicator** — 7px `ok` dot with `box-shadow: 0 0 0 3px rgba(15,157,117,.15)`,
2s ease-in-out opacity breathe. Only on genuinely live data.

**Empty state** — muted sentence in a soft dashed panel; never a bare "0" with no context.
Say what would make it fill.

**Buttons** — primary: accent bg, white text, 9 radius, 10–13px × 16–22px, weight 600.
Ghost: white bg, ink text, `1px solid line`. Disabled: opacity .55.

## Honesty rules (non-negotiable, they're product rules not style)
- Never imply a yield rate. LP language is "fees from real settlement volume."
- Never imply custody. "Credited to your address · withdraw anytime · Tap never holds your funds."
- Label data windows truthfully ("last ~10,000 blocks"), never imply all-time when it isn't.
- Testnet disclosure stays visible on any surface showing balances.

## Where tokens live
- Site: `Tap-Hub/tap-hub/pages/index.js` — `C` and `S` objects (keep values identical to this doc)
- Dashboard: `taprouter/mcp-server/dashboard.js` — `:root` CSS variables (same values)
If a value changes, change it here first, then both surfaces.
