# Ediproof Design DNA — Technical Reference for AuditLens

> Extracted by design analysis agent. Every CSS technique, color ratio, typography decision, and component pattern documented for adaptation.

## Key Takeaway

> "Change the vocabulary, keep the grammar." The grammar is: restrained palette, tracked uppercase labels (letter-spacing: 0.22em), italic serif for emotional weight, hard box-shadows (blur: 0), analog textures (SVG feTurbulence), editorial copy voice. Swap oxblood for teal, swap vellum for cooler paper, and the system remains itself.

## Critical Techniques to Adopt

### 1. Paper Texture (SVG feTurbulence noise)
```css
background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 400 400'...feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4'...%3E");
background-attachment: fixed;
```
- baseFrequency 0.85 = fine paper grain
- feColorMatrix opacity 0.09 = subliminal, felt not seen
- fixed attachment = surface you read ON, not property of elements

### 2. Hard Box-Shadows (stacked paper, no blur)
```css
box-shadow: 0 1px 0 rgba(21,17,13,0.1), 5px 5px 0 vellum-3, 6px 6px 0 ink;
```
- blur: 0 always. No gaussian = no modern "material" feel
- Two offset layers = two sheets of paper stacked

### 3. Label Tracking: letter-spacing 0.22em
- Used on ALL metadata: nav links, form labels, stat labels, table headers, pills, buttons
- 0.22em is 4x typical tracking — reads as engraved metal type
- NEVER vary this value within the label tier

### 4. Section Numerals: 140px column + vertical rule
```css
.section-head { grid-template-columns: 140px 1fr; }
.section-numeral { font-size: 4.5rem; font-style: italic; font-weight: 300; color: brass; border-right: 1px solid ink; }
```

### 5. Wax Seal: radial-gradient + off-center highlight + rotation
- `radial-gradient(circle at 32% 28%, highlight, mid 45%, deep 95%)`
- `transform: rotate(-7deg)` — human hand, never machine-straight
- Two inner rings: dashed (10px inset) + solid (18px inset)
- Spring animation: `cubic-bezier(.22,1.3,.56,1)` for physical stamp drop

### 6. Color Restraint Ratio
- 80% vellum (background), 18% ink (text/borders), 1.5% brass (metadata), 0.5% accent (emphasis)
- Accent (oxblood/teal) appears in: one word per section title, active CTA, active tab, seal, drop cap
- Because 95% is ink-on-vellum, each accent appearance carries enormous weight

### 7. Zero Border-Radius Everywhere
- Never rounded. `border-radius: 0` on buttons, inputs, cards, pills
- Rounded corners = universal tell of modern UI frameworks
- Sharp corners = formal documents, printed forms, ledger entries

### 8. Underline-Only Form Inputs
```css
.field-input { border: none; border-bottom: 1px solid ink; background: transparent; padding: 0.75rem 0; }
```
- No box, no background — "fountain pen on paper"
- Focus: border-bottom goes from 1px to 2px, shifts to accent color

## AuditLens Color Mapping

| Ediproof | AuditLens |
|---|---|
| vellum-1 #f4ecd8 | #F5F3EF (cream) or #f0f7f6 (teal-tinted) |
| vellum-2 #ead9b8 | #e0f0ee |
| vellum-3 #dfc99a | #c8e3e0 |
| oxblood #7a1f2b | teal #115E59 |
| brass #8a6d3b | keep warm brass or use #7a6f5a |
| moss #4a5d3a | teal-light #14b8a6 |

## Do NOT Change
- Animation keyframes and timing values
- feTurbulence parameters (only change feColorMatrix color channels)
- letter-spacing: 0.22em on labels
- border-radius: 0 on all interactive elements
- 5px/6px box-shadow geometry on cards
- Seal rotation angles (-7deg / +5deg)
- Section-head 140px 1fr grid
- line-height: 0.92 on display type
- ::selection { background: accent; color: vellum-1; }
