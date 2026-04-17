# AuditLens — Brand Guidelines & Frontend Design Spec

**Date:** 2026-04-12
**Status:** Draft
**Direction:** Variation B — "The Audit Ledger"

---

## 1. Brand Identity

**Name:** AuditLens
**Tagline:** "See what your data is hiding"
**Personality:** The Research Professor — scholarly, methodical, authoritative. Lets the work speak for itself. Never flashy, never casual.

**Brand voice rules:**
- Formal but not stiff. "Begin Audit" not "Let's go!"
- Labels use structured language: "Act the First", "No. I", section numerals
- Technical terms are used precisely, not dumbed down
- Explanations are clear enough for a non-engineer but never condescending

---

## 2. Color Palette

| Token | Hex | Usage |
|---|---|---|
| `--teal-deep` | `#115E59` | Primary brand color. Headlines, CTAs, shield fill, active states |
| `--teal-mid` | `#0F766E` | Hover states, secondary emphasis |
| `--teal-light` | `#14B8A6` | Status dots, subtle accents (sparingly) |
| `--teal-wash` | `#F0FDFA` | Tinted backgrounds for cards/badges |
| `--cream` | `#F5F3EF` | Page background. Warm, not cold white |
| `--card-white` | `#FFFFFF` | Card/raised surfaces |
| `--ink` | `#1A1A1A` | Primary text |
| `--ink-secondary` | `#4A4A4A` | Body text, descriptions |
| `--ink-muted` | `#7A7A7A` | Captions, metadata, secondary labels |
| `--ink-faint` | `#B0B0B0` | Decorative numerals, dividers |
| `--border` | `#E8E5E0` | Card borders, section separators |
| `--accent-amber` | `#D97706` | Warnings, HITL review flags |
| `--accent-red` | `#B91C1C` | Errors, violations, BLOCK verdicts |
| `--accent-green` | `#15803D` | Success, APPROVE verdicts, passing checks |

**Rules:**
- Cream background everywhere. Never pure white for page surfaces.
- Teal is used for emphasis, never as a large fill area (except shield and CTAs).
- No gradients except on the shield seal element.
- Borders are visible and structural (1-2px solid), not decorative shadows.

---

## 3. Typography

| Role | Font | Weight | Usage |
|---|---|---|---|
| Display | Crimson Pro | 300, 400, 500, 600, 700 | Headlines, section titles, brand wordmark. Italics for emphasis words. |
| Body | IBM Plex Sans | 300, 400, 500, 600 | Paragraphs, navigation, buttons, labels. |
| Mono | IBM Plex Mono | 400, 500 | Code snippets, scan output, hashes, technical metadata. |

**Type scale:**
- Hero headline: 50px, Crimson Pro 300, line-height 1.08
- Section title: 28px, Crimson Pro 400
- Body: 16-17px, IBM Plex Sans 400, line-height 1.65
- Labels: 11-12px, IBM Plex Sans 600, uppercase, letter-spacing 0.12-0.2em
- Mono metadata: 11px, IBM Plex Mono 400

**Rules:**
- Emphasized words in headlines use Crimson Pro italic + teal color
- Section titles follow pattern: "How a scan is *conducted*." (plain + italic-teal)
- Labels are always uppercase with generous letter-spacing
- Brand wordmark: "AUDIT" in Crimson Pro 700 + "Lens" in Crimson Pro 400 italic teal

---

## 4. Visual Metaphor: Shield + Checkmark

The shield is the brand mark. It appears:
- In the landing hero section as a large decorative seal
- As the favicon/logo mark at small sizes
- In dashboard cards as status indicators (shield + check = compliant, shield + X = violation)

**Shield seal specifications:**
- Shape: Rectangle with bottom rounded into a shield point (border-radius: 10px 10px 80px 80px)
- Fill: `--teal-deep` background
- Inner border: 1px solid white at 20% opacity, inset 8px
- Content: Checkmark, "AuditLens", "Verified" subtitle
- Shadow: 0 8px 30px rgba(17,94,89,0.2)

---

## 5. Component Language

### Cards (Steps & Features)
- Background: `--card-white`
- Border: 1px solid `--border`
- Border-radius: 0 (sharp corners — deliberate formality)
- Top accent: 3px solid `--teal-deep` bar at top edge
- Padding: 24px
- No shadows. Elevation communicated through borders only.

### Section Heads
- Pattern: `[Section numeral] + [Title with italic-teal emphasis]`
- Numeral: Crimson Pro italic 300, 28px, teal color
- Separator: bottom border 1px solid `--border`
- Step labels: "Act the First", "Act the Second", "Act the Third" (not "Step 1, 2, 3")

### Navigation
- Top bar with 2px solid ink bottom border
- Brand name left, links right
- Links: 12px uppercase with letter-spacing, underline on hover
- Brand tag: mono font, separated by vertical 1px border

### Buttons
- Primary: `--teal-deep` fill, white text, 4px border-radius (barely rounded), uppercase 14px, letter-spacing 0.04em
- Ghost: transparent, ink text, 1px border, hover → teal border + text
- No pill-shaped buttons. Square-ish is the AuditLens way.

### Footer
- Thick top border (2px solid ink)
- Two columns: brand tagline (left, Crimson italic), tech stack (right, mono)

---

## 6. The Three Pages

### Page 1: Landing Page
**Purpose:** Introduce AuditLens, explain what it does, link to the demo.

**Sections (top to bottom):**
1. **Navigation** — AUDIT*Lens* wordmark + tag, links (Features, The Pipeline, GitHub)
2. **Hero** — Asymmetric 2-column. Left: label + headline + subtitle + CTA. Right: shield seal.
   - Headline: "Your database has compliance *blind spots*. We find them."
   - CTA: "BEGIN AUDIT" button
3. **How It Works** — Section numeral II. Three cards with "Act the First/Second/Third" structure.
4. **Key Features** — Section numeral III. Three feature cards with teal top-accent bars.
5. **Footer** — Thick rule, brand + tech stack.

### Page 2: Chat UI
**Purpose:** The scan interface. User connects DB, uploads PDF, runs scan, sees streaming output.

**Layout:** Full-height, two-panel.
- **Left panel (narrow, ~300px):** Configuration sidebar
  - DB connection form (host, port, user, password, database) OR SQLite file picker
  - PDF upload dropzone
  - "Begin Audit" button
  - Status indicators (connected/disconnected, file uploaded/pending)
- **Right panel (wide):** Chat/streaming output area
  - Claude-style streaming output: tokens appear in real-time
  - Stage indicators: [1/9] Extracting rules... [2/9] Discovering schema...
  - Results appear inline as the scan progresses
  - Final summary card at the end with violation count + link to dashboard

**Styling notes:**
- Left panel: cream background, card-style sections with borders
- Right panel: slightly lighter background, monospace output for scan stages
- Stage progress uses teal numerals: `[1/9]`, `[2/9]`, etc.
- Violations flagged inline with `--accent-red` markers
- Completion shown with shield-check icon + teal "Complete" badge

### Page 3: Dashboard
**Purpose:** Static view of a completed scan's results. Clean cards + KPIs. No interactivity.

**Layout:**
1. **Header bar** — Scan ID, timestamp, DB name, rule count
2. **KPI row** — 4-5 metric cards in a row:
   - Total Violations
   - Tables Scanned
   - Rules Applied
   - Compliance Score (percentage)
   - Scan Duration
3. **Violations by severity** — Simple bar chart or segmented bar (Critical / High / Medium / Low)
4. **Violations by table** — Horizontal bar chart or table-based breakdown
5. **Rule results list** — Vertical list of rules, each showing: rule text, pass/fail status, violation count, confidence score
6. **Recent violations table** — Ledger-style table: row ID, table, column, rule, value, severity

**Styling notes:**
- KPI cards: card-white with teal top-accent bar, large Crimson Pro number, small label underneath
- Charts: simple, teal for normal, amber for warning, red for critical. No 3D, no gradients.
- Violations table: styled like the Ediproof ledger table — clean rows, mono for IDs, alternating subtle backgrounds
- Compliance score: large percentage in teal if >80%, amber if 50-80%, red if <50%

---

## 7. Technical Implementation

- **Single HTML file per page** — self-contained, no build step
- **Shared `styles.css`** — all three pages use one stylesheet (like Ediproof)
- **Google Fonts** — Crimson Pro, IBM Plex Sans, IBM Plex Mono loaded via `@import`
- **No JavaScript framework** — vanilla JS for interactions (tab switching, form handling)
- **Charts** — CSS-only bar charts (no Chart.js dependency) for the dashboard
- **Responsive** — designed for 1280px+ screens (projector), with basic mobile fallback

---

## 8. Files to Create

```
frontend/
  styles.css           # Shared design tokens, typography, components
  index.html           # Landing page
  scan.html            # Chat UI / scan interface
  dashboard.html       # Static results dashboard
```

---

## 9. What This Spec Does NOT Cover

- Backend API integration (the HTML pages are static demos for the presentation)
- Authentication or user accounts
- Mobile-first responsive design (projector-first)
- Dark mode
- Animations beyond basic hover states
- Real streaming (scan output is pre-rendered to look like streaming)
