# Layout Geometry

Rules for the geometry *inside* a module. `data-pptx-bounds` proves that a module sits in its own zone and that two zones do not overlap; it says nothing about a card drawn too short for its text, a chip dropped on a caption, or a band sized from the wrong x. Those defects survive the bounds contract, the canonical-style pass, and the export, and only become visible when the slide is rendered.

This file owns the rule bodies and the numeric tolerances. `scripts/svg_quality/layout_geometry.py` implements them; `scripts/svg_layout_audit.py` runs them over a workspace; `scripts/docs/layout-audit.md` documents the tool. Any other file carries a one-line pointer to this file and no paraphrase.

## 1. When the rules apply

Apply them while authoring each page, and verify once before the final gate:

```bash
python3 scripts/svg_layout_audit.py <project_path>            # exit 1 on an error
python3 scripts/svg_layout_audit.py <project_path> --strict   # exit 1 on any finding
```

They cover authored page SVG (`svg_output/` of a Generate, Edit Native, or template workspace). They do not cover template libraries, chart data payloads, or the exporter's own output.

## 2. Paint order is the contract

An SVG is painted in document order: a later element covers an earlier one. Every rule below is a consequence of that single fact, so the fix is always one of three moves — **resize the carrier**, **move the text**, or **move the element later/earlier in the file**. Never add a scrim to hide a mistake.

## 3. The rules

### L1 — Text is never covered by a later shape

An opaque shape painted after a text run must not cover more than **12%** of that text's box. A shape is opaque when its fill is neither `none` nor `transparent` and `fill-opacity` is at least **0.35**; a shape thinner than **6 px** in either dimension is a decorative rule and never counts as an occluder. An unset `fill` counts as opaque, per the SVG default.

- Severity: **error**
- Canonical fix: the shape was sized from the wrong origin — resize it so it stops at the text, or move the text out of its path. A card that grows downward must also move the cards below it.

### L2 — Two text runs never collide

Two rendered text boxes must not overlap by more than **5%** of the smaller box. Boxes are glyph boxes: width from the measured line, height from `y − 0.78 × size` to `y + 0.24 × size`.

- Severity: **error**
- Canonical fix: separate the baselines by at least the line height, or split one run into two lines. Two labels sharing a baseline must end before the next one starts.

### L3 — Text stays inside the card that holds it

A text run must not run more than **4 px** past the right edge of the smallest opaque shape containing its centre. Full-width bands (at least **85%** of the canvas width) are exempt: inside them the text is aligned to the band, not to a card.

- Severity: **warning**
- Canonical fix: enlarge the card, reduce the run's font by one step, or shorten the wording. Do not trim meaning to satisfy the measure; reflow instead.

### L4 — Text leaves breathing room from the card's bottom edge

A text run's descent must sit at least **3 px** above the bottom edge of its card; a card shorter than **30 px** is a chip and is exempt.

- Severity: **warning**
- Canonical fix: raise the text block by the deficit; never grow the card into the next module's zone to buy the space.

### L5 — A filled block never crosses its panel's border

A panel is a stroked shape. An opaque block whose horizontal extent sits entirely inside that panel must not cross the panel's top or bottom border by more than **4 px**. A block that starts or ends outside the panel's horizontal extent is not the panel's child (a page-wide band) and is not reported.

- Severity: **warning**
- Canonical fix: move the block inside the panel and re-space its contents; if the panel is genuinely too short, grow the panel and move the module below it.

### L6 — A connector never runs through a label

A stroked line must not pass through the inner box of a text run unless an opaque shape painted *between* them hides the crossing. A sequence-diagram message label belongs above its arrow, or on a filled plate drawn after the arrow.

- Severity: **warning**
- Canonical fix: move the label off the line, or draw the label's plate after the line so the plate covers the segment behind it.

### L7 — A dot never sits on a label

A circle or ellipse must not cover more than **25%** of a text box, unless the circle encloses the whole text (a numbered badge).

- Severity: **warning**
- Canonical fix: move the dot to the label's leading edge, or drop it.

### L8 — Nothing leaves the canvas

Every text box must sit inside the `viewBox`; pass `--margin` to enforce an additional inset (for example `--margin 72` for a deck whose content margin is 72 px).

- Severity: **warning**
- Canonical fix: rewrap or resize the run; a zone that overflows the canvas is a design error, not a bounds error.

## 4. What this rule does not cover

- **Font substitution.** Exported text boxes carry `wrap="none"`, so PowerPoint never reflows a line. A renderer without the deck's face (for example LibreOffice on a machine without `Microsoft YaHei`) may reflow anyway; that is a viewer artifact, not a layout defect, and it is never fixed by trimming wording.
- **Colour, contrast, taste.** Owned by the style lock and the visual review.
- **Distance between modules.** Owned by the bounds contract in [`../../skills/ppt-master/references/shared-standards-core.md`](../../skills/ppt-master/references/shared-standards-core.md) §4.3.
- **Paths.** `polygon`, `rect`, and `circle`/`ellipse` are measured exactly; a `<path>` occluder is not modelled. Author the occluding geometry as a primitive, or keep text clear of the path.

## 5. Tolerances (single source)

| Constant | Value | Rule |
|---|---|---|
| Occlusion coverage | 12% of the text box | L1 |
| Opaque fill threshold | `fill-opacity ≥ 0.35` | L1 |
| Decorative-rule exemption | < 6 px in either dimension | L1 |
| Text–text collision | 5% of the smaller box | L2 |
| Right overflow allowance | 4 px | L3 |
| Full-width band exemption | ≥ 85% of canvas width | L3 |
| Bottom bleed allowance | 3 px | L4 |
| Chip exemption | card height < 30 px | L4 |
| Panel-border crossing | 4 px | L5 |
| Dot coverage | 25% of the text box | L7 |

Change a number here first, then in `scripts/svg_quality/layout_geometry.py`; a value that disagrees is a defect.
