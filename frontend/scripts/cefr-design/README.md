# CEFR colour scale: provenance

The design decision behind the six-level CEFR scale (four hues; A1 outline,
C2 solid; washes 12/24/34/40%).

- `cefr-preview.html` - the proposal as approved: the ladder and a plate per
  theme.
- `cmath.py`, `themes.py`, `table.py`, `gen.py` - the designer's measurement
  scripts (OKLab dE, WCAG contrast, Machado colour-blind simulation) and
  the theme tokens they used. `table.json` is their output.

These are the record, not the gate. The enforced check is
`../check-cefr-contrast.mjs`, run by `npm run lint`: it parses the real
themes out of `src/styles/globals.css` and reproduces these figures (for
example Serika Dark washes 1.50 / 1.76 / 2.02, pen 2.28, worst chip 4.66).
