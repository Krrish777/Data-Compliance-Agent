# Figures — Data Compliance Agent Project Report

This directory contains every figure referenced by the chapters in `report/` except:

- **Fig. 2.4** — Level-1 DFD scanner pipeline (covered by `../../data/Screenshot 2026-02-22 105730.png`, referenced from top-level `README.md`)
- **Fig. 2.7** — Activity diagram scanner happy path (covered by same screenshot)
- **Fig. 2.8** — Sequence diagram scanner end-to-end (covered by same screenshot)
- **Fig. 4.2** — Sample compliance-report HTML (user will paste a real browser screenshot)

## Figure index

| Fig. No. | Title | Source file | Rendered PNG | Injected at heading |
|---|---|---|---|---|
| 2.1 | High-level block diagram (3-layer) | `fig_2_1_block_diagram.excalidraw` | `fig_2_1_block_diagram.png` | `03_design.md` — `## 2.1 Block Diagram` |
| 2.2 | Entity-Relationship diagram (crow's-foot) | `fig_2_2_erd.excalidraw` | `fig_2_2_erd.png` | `03_design.md` — `## 2.2 Entity-Relationship Diagram` |
| 2.3 | Level-0 DFD (context) | `fig_2_3_dfd_level0_context.excalidraw` | `fig_2_3_dfd_level0_context.png` | `03_design.md` — `### 2.3.1 Level-0 Context` |
| 2.5 | Level-1 DFD interceptor pipeline | `fig_2_5_dfd_level1_interceptor.excalidraw` | `fig_2_5_dfd_level1_interceptor.png` | `03_design.md` — `### 2.3.3 Level-1 Decomposition — Interceptor Pipeline` |
| 2.6 | Use-case diagram (UML) | `fig_2_6_use_case.excalidraw` | `fig_2_6_use_case.png` | `03_design.md` — `## 2.4 Use Case Diagram` |
| 2.9 | Sequence diagram — interceptor with retry loop | `fig_2_9_sequence_interceptor.excalidraw` | `fig_2_9_sequence_interceptor.png` | `03_design.md` — `### 2.6.2 Interceptor — Sequence with Retry Loop` |
| 4.1 | Test pyramid | `fig_4_1_test_pyramid.excalidraw` | `fig_4_1_test_pyramid.png` | `05_testing.md` — `## 4.1 Testing Strategy` |
| 4.3 | Keyset vs. OFFSET pagination latency | `fig_4_3_keyset_vs_offset.excalidraw` | `fig_4_3_keyset_vs_offset.png` | `05_testing.md` — `### 4.5` (after keyset-vs-OFFSET paragraph) |

## Editing

Each `.excalidraw` file is a pure JSON document. To edit:

1. Open https://excalidraw.com (or the VS Code Excalidraw extension).
2. File → Open → choose the `.excalidraw` file.
3. Edit and save. To re-export a PNG run:
   ```bash
   cd ../../.claude/skills/excalidraw-diagram/references
   uv run python render_excalidraw.py ../../../report/figures/fig_N_N_slug.excalidraw
   ```

All diagrams use:

- `roughness: 0` (clean/crisp edges)
- `opacity: 100` (no transparency)
- Semantic colors pulled from `.claude/skills/excalidraw-diagram/references/color-palette.md`
- `fontFamily: 3` (monospace)

## Conventions

- `F*`-prefixed labels in DFDs identify data flows numerically.
- `D*`-prefixed rectangles are persistent data stores.
- `UC*`-prefixed ellipses are use cases; `«extend»` / `«include»` relationships are dashed.
- Sequence-diagram lifelines are dashed vertical lines; activation bars are grey rectangles.
- The retry loop in Fig. 2.9 is enclosed in a red UML `loop [retry ≤ 3]` combined fragment.
