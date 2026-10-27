#!/usr/bin/env python3
"""Audit authored slide SVG for geometric layout defects.

Checks what `data-pptx-bounds` cannot: text hidden behind a later shape, text
colliding with text, labels running past or bleeding on their card, bands
crossing a panel border, connectors cutting through labels.  Rules and
tolerances are owned by `docs/rules/layout-geometry.md`.

Usage:
    python3 skills/ppt-master/scripts/svg_layout_audit.py <project_or_svg_dir>
    python3 skills/ppt-master/scripts/svg_layout_audit.py <dir> --strict --json /tmp/layout.json

Exit code: 0 when clean (or only warnings), 1 when an error is found, and with
--strict 1 when anything at all is found.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from svg_quality.layout_geometry import audit_document  # noqa: E402

MAX_REPORTED_PER_FILE = 12


def _resolve_target(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() == '.svg':
        return [path]
    if not path.is_dir():
        raise SystemExit(f'[ERROR] not a directory or .svg file: {path}')
    svg_output = path / 'svg_output'
    root = svg_output if svg_output.is_dir() else path
    return sorted(
        (p for p in root.glob('*.svg')),
        key=lambda p: (len(p.stem.split('_')[0]), p.stem),
    )


def _audit_file(path: Path, margin: float) -> tuple[list[dict], str | None]:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [], f'XML parse error: {exc}'
    findings = audit_document(root, margin=margin)
    payload = []
    for finding in findings:
        payload.append({
            'code': finding.code,
            'severity': finding.severity,
            'message': finding.message,
            'element': finding.element,
            'rect': [round(value, 1) for value in finding.rect],
        })
    return payload, None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='svg_layout_audit.py',
        description='Detect overlap, occlusion, overflow and bleed in slide SVG.',
    )
    parser.add_argument('target', help='project directory, svg_output directory, or one .svg')
    parser.add_argument('--margin', type=float, default=0.0,
                        help='extra safe-area margin inside the canvas (default 0)')
    parser.add_argument('--strict', action='store_true',
                        help='treat warnings as failures too')
    parser.add_argument('--json', metavar='PATH', help='also write a JSON report here')
    parser.add_argument('--max-per-file', type=int, default=MAX_REPORTED_PER_FILE,
                        help=f'cap printed findings per file (default {MAX_REPORTED_PER_FILE})')
    parser.add_argument('--quiet', action='store_true', help='print the summary only')
    return parser


def main(argv: list[str] | None = None) -> int:
    configure = getattr(sys.stdout, 'reconfigure', None)
    if configure is not None:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    args = build_parser().parse_args(argv)
    targets = _resolve_target(Path(args.target))
    if not targets:
        print('[ERROR] no .svg files found')
        return 1

    report: dict[str, list[dict]] = {}
    parse_errors: dict[str, str] = {}
    errors = warnings = 0
    dirty_files = 0

    for path in targets:
        findings, parse_error = _audit_file(path, args.margin)
        if parse_error:
            parse_errors[path.name] = parse_error
            continue
        if not findings:
            continue
        dirty_files += 1
        report[path.name] = findings
        file_errors = sum(1 for f in findings if f['severity'] == 'error')
        file_warnings = len(findings) - file_errors
        errors += file_errors
        warnings += file_warnings
        if args.quiet:
            continue
        print(f'[FILE] {path.name}  ({file_errors} error, {file_warnings} warning)')
        for finding in findings[:args.max_per_file]:
            print(f"  [{finding['severity'].upper():7}] {finding['code']:<12} {finding['message']}")
        hidden = len(findings) - args.max_per_file
        if hidden > 0:
            print(f'  ... {hidden} more finding(s) suppressed')

    for name, message in parse_errors.items():
        print(f'[FILE] {name}  [ERROR] {message}')
        errors += 1

    print()
    print(f'[SUMMARY] {len(targets)} file(s), {dirty_files} with findings, '
          f'{errors} error(s), {warnings} warning(s)')
    if args.json:
        Path(args.json).write_text(
            json.dumps({
                'files': report,
                'parse_errors': parse_errors,
                'summary': {
                    'files': len(targets),
                    'files_with_findings': dirty_files,
                    'errors': errors,
                    'warnings': warnings,
                },
            }, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        print(f'[REPORT] {args.json}')

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
