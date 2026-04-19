# Project Report — Data Compliance Agent

This directory contains the complete project report, broken into chapter files for ease of editing, printing, and conversion to other formats.

## File order

Read or print the files in this exact order:

| # | File | Section |
|---|---|---|
| 1 | `00_cover_and_toc.md` | Cover, certificate, declaration, acknowledgement, abstract, TOC, lists |
| 2 | `01_synopsis.md` | Standalone Synopsis (7-8 pages) |
| 3 | `02_introduction.md` | Chapter 1 — Introduction |
| 4 | `03_design.md` | Chapter 2 — Design |
| 5 | `04_implementation.md` | Chapter 3 — Implementation |
| 6 | `05_testing.md` | Chapter 4 — Testing |
| 7 | `06_conclusion_future.md` | Chapter 5 — Conclusion and Future Scope |
| 8 | `07_references.md` | Chapter 6 — References |

## Conversion to Word (.docx)

If `pandoc` is installed:

```bash
cd report
pandoc 00_cover_and_toc.md 01_synopsis.md 02_introduction.md \
       03_design.md 04_implementation.md 05_testing.md \
       06_conclusion_future.md 07_references.md \
       -o final_report.docx --toc --toc-depth=3
```

If a custom Word template (`template.docx`) is required by the institution, add `--reference-doc=template.docx`.

## Conversion to PDF

The simplest path is to print each Markdown file from VS Code's built-in Markdown preview (right-click → "Open Preview" → Ctrl-P → "Print"). This produces a clean PDF that respects all tables, headings and code blocks.

For a single combined PDF via pandoc + LaTeX:

```bash
pandoc 00_cover_and_toc.md ... 07_references.md -o final_report.pdf \
       --pdf-engine=xelatex --toc --toc-depth=3 \
       -V geometry:a4paper,margin=1in -V mainfont="Calibri"
```

## Inserting the prepared diagrams

The user has prepared the following figures separately (see Chapter 2 captions). Insert each figure at the marked position by replacing the corresponding paragraph header in `03_design.md`:

| Caption | Insert in | After heading |
|---|---|---|
| Fig. 2.1 — High-level block diagram | `03_design.md` | "## 2.1 Block Diagram" |
| Fig. 2.2 — ERD | `03_design.md` | "## 2.2 Entity-Relationship Diagram" |
| Figs. 2.3-2.5 — DFDs | `03_design.md` | "## 2.3 Data Flow Diagrams" |
| Fig. 2.6 — Use Case Diagram | `03_design.md` | "## 2.4 Use Case Diagram" |
| Fig. 2.7 — Activity Diagram | `03_design.md` | "## 2.5 Activity Diagram" |
| Figs. 2.8-2.9 — Sequence Diagrams | `03_design.md` | "## 2.6 Sequence Diagrams" |

For Word: Insert → Pictures → choose file. For pandoc-PDF: replace the heading line with `![Caption](path/to/figure.png)` and re-render.

## Word-count and page-count check

Run from this directory:

```bash
wc -w *.md
```

Approximate page count: total words ÷ 300 (at 12 pt, 1.5 line spacing on A4).

## Notes for the viva

- Every numbered objective in §1.3 is mapped to a concrete `file:line` location — be ready to open the file at that line and explain the code.
- The end-to-end run numbers (62 raw rules → 17 structured → 11,775 violations in 246.6 s, score 58.8 %, Grade D) are reproducible with `python run_hi_small.py` provided `GROQ_API_KEY` is set.
- Six security fixes (commits `0ecd609`, `a7b7792`, `8361ba0`, `7fe13ee`, `4ee19d7`, `10b7f02`) are described in §4.6 and each is guarded by a regression test.
- The 47-entry references list in `07_references.md` uses arXiv IDs, DOIs, and official documentation URLs wherever available.
