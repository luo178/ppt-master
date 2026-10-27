#!/usr/bin/env python3
"""Geometric layout audit for authored slide SVG.

The bounds contract (`data-pptx-bounds`) only proves that a module stays inside
its own rectangle and that two modules do not overlap.  It says nothing about
what happens *inside* a module: a card drawn too short for its text lets the
next card paint over the last line, a chip dropped on a caption hides it, a
band sized from the wrong x runs past its panel.  Those are the defects this
module finds, using paint order (document order) plus rendered text width.

Every rule and its tolerance is owned by `docs/rules/layout-geometry.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from xml.etree import ElementTree as ET

from text_measure import measure_text

SVG_NS = 'http://www.w3.org/2000/svg'

# Rule codes.  Keep in sync with docs/rules/layout-geometry.md.
OCCLUDED = 'OCCLUDED'
COLLISION = 'COLLISION'
OVERFLOW = 'OVERFLOW'
BLEED = 'BLEED'
FRAME_CROSS = 'FRAME_CROSS'
LINE_THROUGH = 'LINE_THROUGH'
DOT_ON_TEXT = 'DOT_ON_TEXT'
OUT_OF_CANVAS = 'OUT_OF_CANVAS'

ERROR_CODES = frozenset({OCCLUDED, COLLISION})

# Tolerances.  Each one is a rule in docs/rules/layout-geometry.md §3.
OCCLUSION_RATIO = 0.12
COLLISION_RATIO = 0.05
OVERFLOW_ALLOWANCE_PX = 4.0
BLEED_ALLOWANCE_PX = 3.0
FRAME_CROSS_ALLOWANCE_PX = 4.0
DOT_RATIO = 0.25
MIN_OCCLUDER_THICKNESS = 6.0
OPAQUE_FILL_OPACITY = 0.35
WIDE_BAND_RATIO = 0.85
MIN_CARD_HEIGHT = 30.0
DEFAULT_FAMILY = 'Microsoft YaHei'


@dataclass(frozen=True)
class Finding:
    """One geometric defect on one slide."""

    code: str
    message: str
    element: str = ''
    rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def severity(self) -> str:
        return 'error' if self.code in ERROR_CODES else 'warning'


@dataclass(frozen=True)
class _Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersects(self, other: '_Box') -> tuple[float, float]:
        return (
            min(self.x1, other.x1) - max(self.x0, other.x0),
            min(self.y1, other.y1) - max(self.y0, other.y0),
        )

    def coverage_of(self, other: '_Box') -> float:
        """Fraction of ``other`` hidden by ``self`` (area-weighted)."""
        ox, oy = self.intersects(other)
        if ox <= 0 or oy <= 0 or other.area <= 0:
            return 0.0
        return (ox * oy) / other.area

    def overlap_ratio(self, other: '_Box') -> float:
        ox, oy = self.intersects(other)
        small = min(self.area, other.area)
        if ox <= 0 or oy <= 0 or small <= 0:
            return 0.0
        return (ox * oy) / small

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def contains(self, other: '_Box') -> bool:
        return (
            self.x0 <= other.x0 and self.y0 <= other.y0
            and self.x1 >= other.x1 and self.y1 >= other.y1
        )


@dataclass(frozen=True)
class _Text:
    order: int
    text: str
    box: _Box
    anchor: str
    element: str


@dataclass(frozen=True)
class _Shape:
    order: int
    box: _Box
    kind: str
    opaque: bool
    stroked: bool
    element: str


@dataclass(frozen=True)
class _Line:
    order: int
    x1: float
    y1: float
    x2: float
    y2: float


def _number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _first_family(value: str | None) -> str:
    if not value:
        return DEFAULT_FAMILY
    return value.split(',')[0].strip().strip('"\'') or DEFAULT_FAMILY


def _opacity(element: ET.Element, name: str) -> float:
    raw = element.get(name)
    if raw is None:
        return 1.0
    try:
        return max(0.0, min(1.0, float(raw)))
    except ValueError:
        return 1.0


def _element_name(element: ET.Element, order: int) -> str:
    for key in ('id',):
        if element.get(key):
            return f'{element.tag.split("}")[-1]}#{element.get(key)}'
    return f'{element.tag.split("}")[-1]}[{order}]'


def _walk(root: ET.Element):
    """Yield (element, order, inherited_style) in document (paint) order."""
    counter = 0

    def visit(element: ET.Element, inherited: dict[str, str]):
        nonlocal counter
        current = dict(inherited)
        for key in ('font-size', 'font-family', 'text-anchor'):
            value = element.get(key)
            if value is not None:
                current[key] = value
        order = counter
        counter += 1
        yield element, order, current
        for child in element:
            yield from visit(child, current)

    yield from visit(root, {})


def _text_lines(element: ET.Element, inherited: dict[str, str]):
    """Split a <text> into rendered lines: (text, x, baseline, anchor)."""
    size = _number(inherited.get('font-size'), 16.0) or 16.0
    anchor = inherited.get('text-anchor', 'start')
    base_x = _number(element.get('x'))
    base_y = _number(element.get('y'))
    own_anchor = element.get('text-anchor', anchor)

    spans = [child for child in element if child.tag.split('}')[-1] == 'tspan']
    if not spans:
        text = ''.join(element.itertext()).strip()
        return [(text, base_x, base_y, own_anchor)] if text else []

    lines: list[tuple[str, float, float, str]] = []
    buffer = (element.text or '').strip()
    cursor_x, cursor_y = base_x, base_y
    for span in spans:
        piece = ''.join(span.itertext()).strip()
        dy = span.get('dy')
        dx = span.get('dx')
        span_x = span.get('x')
        span_y = span.get('y')
        starts_line = any(v is not None for v in (dy, dx, span_x, span_y))
        if starts_line and buffer:
            lines.append((buffer, cursor_x, cursor_y, own_anchor))
            buffer = ''
        if starts_line:
            if dy is not None:
                cursor_y += _number(dy)
            if dx is not None:
                cursor_x += _number(dx)
            if span_x is not None:
                cursor_x = _number(span_x)
            if span_y is not None:
                cursor_y = _number(span_y)
        buffer += piece
    if buffer:
        lines.append((buffer, cursor_x, cursor_y, own_anchor))
    return lines


def _line_box(text: str, x: float, baseline: float, size: float,
              family: str, anchor: str) -> _Box:
    width = measure_text(text, size=size, family=family)
    if anchor == 'middle':
        x0 = x - width / 2
    elif anchor == 'end':
        x0 = x - width
    else:
        x0 = x
    return _Box(x0, baseline - size * 0.78, x0 + width, baseline + size * 0.24)


def _collect(root: ET.Element) -> tuple[list[_Text], list[_Shape], list[_Line]]:
    texts: list[_Text] = []
    shapes: list[_Shape] = []
    lines: list[_Line] = []
    for element, order, style in _walk(root):
        tag = element.tag.split('}')[-1]
        name = _element_name(element, order)
        if tag == 'text':
            size = _number(style.get('font-size'), 16.0) or 16.0
            family = _first_family(style.get('font-family'))
            for piece, x, baseline, anchor in _text_lines(element, style):
                texts.append(_Text(
                    order=order,
                    text=piece,
                    box=_line_box(piece, x, baseline, size, family, anchor),
                    anchor=anchor,
                    element=name,
                ))
        elif tag in ('rect', 'circle', 'ellipse', 'polygon'):
            box = _shape_box(tag, element)
            if box is None:
                continue
            fill = element.get('fill', '#000000')
            opaque = (
                fill not in ('none', 'transparent')
                and _opacity(element, 'fill-opacity') >= OPAQUE_FILL_OPACITY
            )
            stroke = element.get('stroke', 'none')
            shapes.append(_Shape(
                order=order,
                box=box,
                kind=tag,
                opaque=opaque,
                stroked=stroke not in ('none', 'transparent'),
                element=name,
            ))
        elif tag in ('line', 'polyline'):
            if element.get('stroke', 'none') in ('none', 'transparent'):
                continue
            if tag == 'line':
                lines.append(_Line(
                    order=order,
                    x1=_number(element.get('x1')),
                    y1=_number(element.get('y1')),
                    x2=_number(element.get('x2')),
                    y2=_number(element.get('y2')),
                ))
    return texts, shapes, lines


def _shape_box(tag: str, element: ET.Element) -> _Box | None:
    if tag == 'rect':
        x, y = _number(element.get('x')), _number(element.get('y'))
        w, h = _number(element.get('width')), _number(element.get('height'))
        if w <= 0 or h <= 0:
            return None
        return _Box(x, y, x + w, y + h)
    if tag in ('circle', 'ellipse'):
        cx, cy = _number(element.get('cx')), _number(element.get('cy'))
        if tag == 'circle':
            rx = ry = _number(element.get('r'))
        else:
            rx, ry = _number(element.get('rx')), _number(element.get('ry'))
        if rx <= 0 or ry <= 0:
            return None
        return _Box(cx - rx, cy - ry, cx + rx, cy + ry)
    if tag == 'polygon':
        raw = (element.get('points') or '').strip()
        values = [v for v in raw.replace(',', ' ').split() if v]
        try:
            numbers = [float(v) for v in values]
        except ValueError:
            return None
        xs, ys = numbers[0::2], numbers[1::2]
        if not xs or not ys:
            return None
        return _Box(min(xs), min(ys), max(xs), max(ys))
    return None


def _host_card(text: _Text, shapes: Iterable[_Shape]) -> _Shape | None:
    """The smallest earlier opaque shape that holds the text's start point."""
    host: _Shape | None = None
    for shape in shapes:
        if shape.order >= text.order or not shape.opaque:
            continue
        centre_x = (text.box.x0 + text.box.x1) / 2
        centre_y = (text.box.y0 + text.box.y1) / 2
        if not shape.box.contains_point(centre_x, centre_y):
            continue
        if host is None or shape.box.area < host.box.area:
            host = shape
    return host


def _hides(shape: _Shape, x: float, y: float, after: int, before: int) -> bool:
    """True when ``shape`` (opaque, painted between two orders) covers a point."""
    return (
        shape.opaque
        and after < shape.order < before
        and shape.box.contains_point(x, y)
    )


def _line_crosses(seg: _Line, box: _Box) -> tuple[float, float] | None:
    inset_x = (box.x1 - box.x0) * 0.08
    inset_y = (box.y1 - box.y0) * 0.10
    x0, x1 = box.x0 + inset_x, box.x1 - inset_x
    y0, y1 = box.y0 + inset_y, box.y1 - inset_y
    steps = 48
    for step in range(1, steps):
        t = step / steps
        px = seg.x1 + (seg.x2 - seg.x1) * t
        py = seg.y1 + (seg.y2 - seg.y1) * t
        if x0 < px < x1 and y0 < py < y1:
            return px, py
    return None


def _fmt(box: _Box) -> str:
    return f'{box.x0:.0f},{box.y0:.0f} {box.width:.0f}x{box.height:.0f}'


def audit_document(root: ET.Element, *, margin: float = 0.0) -> list[Finding]:
    """Return every geometric defect in one slide SVG, in document order."""
    texts, shapes, lines = _collect(root)
    canvas_width = _canvas_width(root)
    findings: list[Finding] = []

    # 1. Text hidden by a shape painted on top of it.  Thin decorative rules
    #    (underlines, hairlines) are not occluders, and the ratio is measured
    #    against the text box so a small chip cannot report 100%.
    for text in texts:
        for shape in shapes:
            if shape.order <= text.order or not shape.opaque:
                continue
            if min(shape.box.width, shape.box.height) < MIN_OCCLUDER_THICKNESS:
                continue
            ratio = shape.box.coverage_of(text.box)
            if ratio >= OCCLUSION_RATIO:
                findings.append(Finding(
                    code=OCCLUDED,
                    message=(
                        f"text {text.text!r} at {_fmt(text.box)} is covered by "
                        f"{shape.kind} {_fmt(shape.box)} painted later "
                        f'({ratio:.0%} of the text hidden)'
                    ),
                    element=text.element,
                    rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
                ))
                break

    # 2. Two text runs colliding.
    for index, first in enumerate(texts):
        for second in texts[index + 1:]:
            ratio = first.box.overlap_ratio(second.box)
            if ratio >= COLLISION_RATIO:
                findings.append(Finding(
                    code=COLLISION,
                    message=(
                        f"text {first.text!r} at {_fmt(first.box)} collides with "
                        f'{second.text!r} at {_fmt(second.box)} ({ratio:.0%})'
                    ),
                    element=first.element,
                    rect=(first.box.x0, first.box.y0, first.box.x1, first.box.y1),
                ))

    # 3. Text running past the card that holds it, and 4. text bleeding on the
    #    card's bottom edge.
    for text in texts:
        host = _host_card(text, shapes)
        if host is None:
            continue
        if host.box.width < WIDE_BAND_RATIO * canvas_width:
            overflow = text.box.x1 - host.box.x1
            if overflow > OVERFLOW_ALLOWANCE_PX:
                findings.append(Finding(
                    code=OVERFLOW,
                    message=(
                        f"text {text.text!r} runs {overflow:.0f}px past its card "
                        f'(card {_fmt(host.box)})'
                    ),
                    element=text.element,
                    rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
                ))
        if host.box.height >= MIN_CARD_HEIGHT:
            gap = host.box.y1 - text.box.y1
            if gap < BLEED_ALLOWANCE_PX:
                findings.append(Finding(
                    code=BLEED,
                    message=(
                        f"text {text.text!r} sits {gap:.1f}px from the bottom edge "
                        f'of its card {_fmt(host.box)}; leave at least '
                        f'{BLEED_ALLOWANCE_PX:.0f}px'
                    ),
                    element=text.element,
                    rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
                ))

    # 5. A filled block crossing the border of the panel that contains it.
    frames = [s for s in shapes if s.stroked]
    for frame in frames:
        for shape in shapes:
            if shape is frame or not shape.opaque or shape.order < frame.order:
                continue
            if frame.box.area <= shape.box.area:
                continue
            # Only blocks that sit horizontally inside the panel can "belong"
            # to it; a page-wide band is not a panel child.
            if not (frame.box.x0 <= shape.box.x0 and shape.box.x1 <= frame.box.x1):
                continue
            crosses_bottom = (
                shape.box.y0 < frame.box.y1 <= shape.box.y1 + FRAME_CROSS_ALLOWANCE_PX
                and shape.box.y1 > frame.box.y1 + FRAME_CROSS_ALLOWANCE_PX
            )
            crosses_top = (
                shape.box.y1 > frame.box.y0 >= shape.box.y0 - FRAME_CROSS_ALLOWANCE_PX
                and shape.box.y0 < frame.box.y0 - FRAME_CROSS_ALLOWANCE_PX
            )
            if crosses_bottom or crosses_top:
                findings.append(Finding(
                    code=FRAME_CROSS,
                    message=(
                        f"block {shape.element} {_fmt(shape.box)} crosses the "
                        f'border of panel {frame.element} {_fmt(frame.box)}'
                    ),
                    element=shape.element,
                    rect=(shape.box.x0, shape.box.y0, shape.box.x1, shape.box.y1),
                ))

    # 6. A connector line crossing a label it was not drawn behind.
    for text in texts:
        for segment in lines:
            hit = _line_crosses(segment, text.box)
            if hit is None:
                continue
            if any(_hides(shape, hit[0], hit[1], segment.order, text.order)
                   for shape in shapes):
                continue
            findings.append(Finding(
                code=LINE_THROUGH,
                message=(
                    f"connector {segment.x1:.0f},{segment.y1:.0f}->"
                    f'{segment.x2:.0f},{segment.y2:.0f} crosses text '
                    f'{text.text!r} at {_fmt(text.box)}'
                ),
                element=text.element,
                rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
            ))

    # 7. A dot sitting on top of a label.  A numbered badge (the dot encloses
    #    the label) is intentional and never reported.
    for text in texts:
        for shape in shapes:
            if shape.kind not in ('circle', 'ellipse') or not shape.opaque:
                continue
            if shape.box.contains(text.box):
                continue
            if shape.box.coverage_of(text.box) >= DOT_RATIO:
                findings.append(Finding(
                    code=DOT_ON_TEXT,
                    message=(
                        f'{shape.kind} {_fmt(shape.box)} sits on text '
                        f'{text.text!r} at {_fmt(text.box)}'
                    ),
                    element=text.element,
                    rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
                ))

    # 8. Anything painted outside the canvas (minus the requested margin).
    canvas = _canvas_box(root)
    if canvas is not None:
        inner = _Box(canvas.x0 + margin, canvas.y0 + margin,
                     canvas.x1 - margin, canvas.y1 - margin)
        for text in texts:
            if not inner.contains(text.box):
                findings.append(Finding(
                    code=OUT_OF_CANVAS,
                    message=(
                        f'text {text.text!r} at {_fmt(text.box)} leaves the canvas '
                        f'safe area {_fmt(inner)}'
                    ),
                    element=text.element,
                    rect=(text.box.x0, text.box.y0, text.box.x1, text.box.y1),
                ))

    return findings


def _viewbox(root: ET.Element) -> tuple[float, float, float, float] | None:
    raw = (root.get('viewBox') or '').replace(',', ' ').split()
    if len(raw) != 4:
        return None
    try:
        values = [float(v) for v in raw]
    except ValueError:
        return None
    return values[0], values[1], values[2], values[3]


def _canvas_box(root: ET.Element) -> _Box | None:
    view = _viewbox(root)
    if view is None:
        return None
    x, y, w, h = view
    return _Box(x, y, x + w, y + h)


def _canvas_width(root: ET.Element) -> float:
    box = _canvas_box(root)
    return box.width if box else 1280.0
