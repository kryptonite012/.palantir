# Project overview: document and slides

| File | What it is |
|---|---|
| [`Project-Atlas-Technical-Overview.pdf`](Project-Atlas-Technical-Overview.pdf) | 46-page technical overview and system guide (A4, bookmarked, 25 figures) |
| [`Project-Atlas-Presentation.pptx`](Project-Atlas-Presentation.pptx) | 24-slide presentation (16:9) with speaker notes on every slide |
| [`Project-Atlas-Presentation.pdf`](Project-Atlas-Presentation.pdf) | PDF export of the slides for viewing without PowerPoint |

Both documents describe release 0.2.0. Their facts come from the repository itself: the README, `docs/`,
the backend and frontend sources, `sample-data/expected_results.json` and the recorded test, acceptance and
benchmark results.

## What the PDF covers

1. Executive summary · 2. Vision, principles and scope · 3. Capabilities at a glance · 4. System architecture ·
5. Codebase tour · 6. Data model and provenance · 7. Ingestion and data quality · 8. Ontology and entity resolution ·
9. Knowledge graph · 10. Search and document intelligence · 11. Timeline, maps and analytics · 12. Optional local AI ·
13. Investigations, workflows and reports · 14. Security model · 15. Audit, backup and offline assurance ·
16. Deployment and operations · 17. Guided tour (Northwind Harbor demo) · 18. API reference overview ·
19. Testing, validation and performance · 20. Status, limitations and roadmap · Appendix A: glossary ·
Appendix B: frequently asked questions

## Regenerating

The sources are in [`source/`](source/). Run these from the `project-atlas/` directory.

PDF (Python 3.11+, ReportLab and Pillow; it uses the Carlito, JetBrains Mono and DejaVu fonts installed on the system):

```bash
python3 docs/overview/source/build_pdf.py
```

Slides (Node 20+):

```bash
npm install --prefix /tmp/atlas-deck pptxgenjs@3.12.0 react-icons@5.3.0 react@18.3.1 react-dom@18.3.1 sharp@0.33.5
```

```bash
NODE_PATH=/tmp/atlas-deck/node_modules node docs/overview/source/build_deck.js
```

To export the slides as PDF, open the `.pptx` in PowerPoint or LibreOffice and save it as PDF.
