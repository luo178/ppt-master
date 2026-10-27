#!/usr/bin/env python3
"""Regressions for the geometric layout audit (L1-L8)."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import svg_layout_audit  # noqa: E402
from svg_quality.layout_geometry import (  # noqa: E402
    BLEED,
    COLLISION,
    DOT_ON_TEXT,
    FRAME_CROSS,
    LINE_THROUGH,
    OCCLUDED,
    OUT_OF_CANVAS,
    OVERFLOW,
    audit_document,
)

HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" '
        'font-family="Microsoft YaHei">')
TAIL = '</svg>'


def audit(body: str, *, margin: float = 0.0):
    root = ET.fromstring(HEAD + body + TAIL)
    return audit_document(root, margin=margin)


def codes(body: str, *, margin: float = 0.0) -> list[str]:
    return [finding.code for finding in audit(body, margin=margin)]


class OcclusionTests(unittest.TestCase):
    def test_card_painted_over_text_is_reported(self) -> None:
        body = (
            '<rect x="80" y="80" width="300" height="60" fill="#12324B"/>'
            '<text x="96" y="100" font-size="13" fill="#FFFFFF">全局表 Global</text>'
            '<text x="96" y="124" font-size="12" fill="#FFFFFF">适合小维表</text>'
            '<rect x="80" y="108" width="300" height="60" fill="#FFFFFF"/>'
        )
        self.assertIn(OCCLUDED, codes(body))

    def test_decorative_hairline_never_occludes(self) -> None:
        body = (
            '<text x="72" y="400" font-size="180" fill="#0E7C86">02</text>'
            '<rect x="72" y="432" width="96" height="4" fill="#0E7C86"/>'
        )
        self.assertEqual(codes(body), [])

    def test_translucent_wash_is_not_an_occluder(self) -> None:
        body = (
            '<rect x="80" y="80" width="300" height="120" fill="#FFFFFF"/>'
            '<text x="96" y="120" font-size="13" fill="#1B2A33">一条说明</text>'
            '<rect x="72" y="60" width="400" height="160" fill="#0E7C86" fill-opacity="0.06"/>'
        )
        self.assertEqual(codes(body), [])


class CollisionTests(unittest.TestCase):
    def test_shared_baseline_collision_is_reported(self) -> None:
        body = (
            '<text x="100" y="200" font-size="24" fill="#12324B">配置与运维</text>'
            '<text x="208" y="200" font-size="18" fill="#5A6B73">部署拓扑与安装</text>'
        )
        self.assertIn(COLLISION, codes(body))

    def test_adjacent_lines_do_not_collide(self) -> None:
        body = (
            '<text x="100" y="200" font-size="15" fill="#1B2A33">第一行说明</text>'
            '<text x="100" y="224" font-size="15" fill="#1B2A33">第二行说明</text>'
        )
        self.assertEqual(codes(body), [])


class CardEdgeTests(unittest.TestCase):
    def test_text_past_the_card_right_edge_is_reported(self) -> None:
        body = (
            '<rect x="100" y="100" width="120" height="40" fill="#F5F5F1"/>'
            '<text x="160" y="126" font-size="12" text-anchor="middle">'
            'TableSpace · Block · OID</text>'
        )
        self.assertIn(OVERFLOW, codes(body))

    def test_text_on_the_card_bottom_edge_is_reported(self) -> None:
        body = (
            '<rect x="100" y="100" width="400" height="60" fill="#F5F5F1"/>'
            '<text x="120" y="160" font-size="15" fill="#1B2A33">贴着下边缘的一行</text>'
        )
        self.assertIn(BLEED, codes(body))


class PanelTests(unittest.TestCase):
    def test_band_crossing_a_panel_border_is_reported(self) -> None:
        body = (
            '<rect x="72" y="148" width="1136" height="246" fill="#FFFFFF" stroke="#C8D0D8"/>'
            '<rect x="88" y="384" width="1104" height="34" fill="#F5F5F1"/>'
        )
        self.assertIn(FRAME_CROSS, codes(body))

    def test_band_inside_the_panel_is_clean(self) -> None:
        body = (
            '<rect x="72" y="148" width="1136" height="246" fill="#FFFFFF" stroke="#C8D0D8"/>'
            '<rect x="88" y="340" width="1104" height="34" fill="#F5F5F1"/>'
        )
        self.assertEqual(codes(body), [])


class ConnectorTests(unittest.TestCase):
    def test_line_through_a_label_is_reported(self) -> None:
        body = (
            '<text x="640" y="250" font-size="13" text-anchor="middle">'
            '① 备机上报当前事务号</text>'
            '<line x1="300" y1="245" x2="880" y2="245" stroke="#0E7C86"/>'
        )
        self.assertIn(LINE_THROUGH, codes(body))

    def test_line_behind_an_opaque_plate_is_clean(self) -> None:
        body = (
            '<line x1="300" y1="245" x2="880" y2="245" stroke="#0E7C86"/>'
            '<rect x="500" y="232" width="280" height="26" fill="#FFFFFF"/>'
            '<text x="640" y="250" font-size="13" text-anchor="middle">'
            '① 备机上报当前事务号</text>'
        )
        self.assertEqual(codes(body), [])


class DotTests(unittest.TestCase):
    def test_dot_on_a_label_is_reported(self) -> None:
        body = (
            '<text x="200" y="200" font-size="14" fill="#1B2A33">说明文字</text>'
            '<circle cx="240" cy="196" r="9" fill="#0E7C86"/>'
        )
        self.assertIn(DOT_ON_TEXT, codes(body))

    def test_numbered_badge_is_clean(self) -> None:
        body = (
            '<circle cx="116" cy="200" r="9" fill="#0E7C86"/>'
            '<text x="116" y="204" font-size="11" fill="#FFFFFF" text-anchor="middle">1</text>'
        )
        self.assertEqual(codes(body), [])


class CanvasTests(unittest.TestCase):
    def test_text_outside_the_canvas_is_reported(self) -> None:
        body = '<text x="1200" y="300" font-size="15" fill="#1B2A33">越界的说明文字</text>'
        self.assertIn(OUT_OF_CANVAS, codes(body))

    def test_margin_inset_is_applied(self) -> None:
        body = '<text x="40" y="300" font-size="15" fill="#1B2A33">贴着左边距</text>'
        self.assertEqual(codes(body), [])
        self.assertIn(OUT_OF_CANVAS, codes(body, margin=72))


class CliTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.write_text(HEAD + body + TAIL, encoding='utf-8')
        return path

    def test_exit_codes_follow_severity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw) / 'proj'
            pages = workspace / 'svg_output'
            pages.mkdir(parents=True)
            self._write(pages, '01_cover.svg',
                        '<text x="100" y="100" font-size="15">干净的一页</text>')
            self._write(pages, '02_broken.svg',
                        '<text x="100" y="200" font-size="24">配置与运维</text>'
                        '<text x="208" y="200" font-size="18">部署拓扑与安装</text>')
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                status = svg_layout_audit.main([str(workspace)])
            self.assertEqual(status, 1)
            self.assertIn('02_broken.svg', buffer.getvalue())
            self.assertIn('COLLISION', buffer.getvalue())

    def test_strict_promotes_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pages = Path(raw)
            self._write(pages, '01_warn.svg',
                        '<rect x="100" y="100" width="400" height="60" fill="#F5F5F1"/>'
                        '<text x="120" y="160" font-size="15">贴着下边缘的一行</text>')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(svg_layout_audit.main([str(pages)]), 0)
                self.assertEqual(
                    svg_layout_audit.main([str(pages), '--strict']), 1)

    def test_json_report_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pages = Path(raw)
            self._write(pages, '01_broken.svg',
                        '<text x="100" y="200" font-size="24">配置与运维</text>'
                        '<text x="208" y="200" font-size="18">部署拓扑与安装</text>')
            report = Path(raw) / 'report.json'
            with contextlib.redirect_stdout(io.StringIO()):
                svg_layout_audit.main([str(pages), '--json', str(report)])
            payload = json.loads(report.read_text(encoding='utf-8'))
            self.assertEqual(payload['summary']['errors'], 1)
            self.assertIn('01_broken.svg', payload['files'])


if __name__ == '__main__':
    unittest.main()
