# `svg_layout_audit.py`

Geometric layout audit for authored slide SVG. Rules and tolerances are owned by [`docs/rules/layout-geometry.md`](../../../../docs/rules/layout-geometry.md); this page documents the tool only.

## Why it exists

`svg_quality_checker.py` verifies that each module stays inside its `data-pptx-bounds` zone and that zones do not overlap. It does not look inside a module, so a card drawn too short for its text — letting the next card paint over the last line — passes every gate and only shows up when the slide is rendered. This audit closes that gap with the eight rules in the geometry doc.

## Usage

```bash
# whole workspace: resolves <path>/svg_output when present, else <path>/*.svg
python3 scripts/svg_layout_audit.py <project_path>

# fail on warnings too, and keep a machine-readable report
python3 scripts/svg_layout_audit.py <project_path> --strict --json /tmp/layout.json

# enforce an extra safe-area inset (deck content margin)
python3 scripts/svg_layout_audit.py <project_path> --margin 72

# one page while repairing
python3 scripts/svg_layout_audit.py <project_path>/svg_output/15_sharding.svg
```

Exit code is `0` when no error is found, `1` when an error is found, and with `--strict` `1` when any finding at all is found. XML that does not parse is reported as an error for that file.

## Output

```
[FILE] 15_sharding.svg  (2 error, 0 warning)
  [ERROR  ] OCCLUDED     text '适合小维表，JOIN 无需跨分片' at 104,223 173x12 is covered by
                         rect 88,228 300x58 painted later (56% of the text hidden)
[SUMMARY] 56 file(s), 1 with findings, 2 error(s), 0 warning(s)
```

`--json` writes `{files: {name: [finding…]}, parse_errors, summary}`, where each finding carries `code`, `severity`, `message`, `element`, and `rect` in canvas coordinates.

## Codes and repairs

| Code | Severity | What it means | Repair |
|---|---|---|---|
| `OCCLUDED` | error | A later opaque shape covers the text | Resize or move the shape; move the text out of its path |
| `COLLISION` | error | Two text runs overlap | Separate the baselines or split a line |
| `OVERFLOW` | warning | Text runs past its card's right edge | Widen the card, step the font down, or reflow |
| `BLEED` | warning | Text sits on its card's bottom edge | Raise the text block |
| `FRAME_CROSS` | warning | A filled block crosses a panel border | Move the block inside, or grow the panel |
| `LINE_THROUGH` | warning | A connector crosses a label | Move the label, or plate it over the line |
| `DOT_ON_TEXT` | warning | A dot covers a label | Move the dot to the leading edge |
| `OUT_OF_CANVAS` | warning | Content leaves the `viewBox` (or the `--margin` inset) | Rewrap or resize |

Each code names one rule in the geometry doc: `OCCLUDED` is L1, `COLLISION` L2, `OVERFLOW` L3, `BLEED` L4, `FRAME_CROSS` L5, `LINE_THROUGH` L6, `DOT_ON_TEXT` L7, `OUT_OF_CANVAS` L8.

## Position in the pipeline

Run it once per consolidated repair pass, before `svg_quality_checker.py --stage final`, then fix every error and the selected warnings in the same pass. It reads the authored SVG only, so run it before `finalize_svg.py` (which rewrites the file) and it stays valid after.

A workspace is clean when the audit reports `0 error, 0 warning`. Errors are always fixed; a warning is fixed or explicitly accepted in the repair note, because each one is visible when the page is rendered.

## Not covered

- Text reflow caused by a viewer that lacks the deck's font — exported boxes carry `wrap="none"`.
- Occluders authored as `<path>` geometry; author them as primitives or keep text clear.
- Colour, contrast, and spacing between modules (bounds contract).
