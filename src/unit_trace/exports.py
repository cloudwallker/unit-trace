"""Text-only SVG and self-contained, script-free HTML snapshots."""

from html import escape
import json

from .models import EvaluationReport, Project, input_error
from .serialization import project_hash

COLORS = {'ok': '#166534', 'warning': '#92400e', 'error': '#b91c1c', 'blocked': '#475569'}


def _current(project: Project, report: EvaluationReport) -> None:
    if report.project_hash != project_hash(project):
        raise input_error('invalid_schema', 'report.projectHash', 'Report does not match the current project.')


def render_svg(project: Project, report: EvaluationReport) -> str:
    _current(project, report)
    labels = {n.id: n.label for n in (*project.variables, *project.formulas)}
    levels = {}
    rows = {}
    positions = {}
    for identifier in report.topological_order:
        level = max((levels[a] + 1 for a, b in report.edges if b == identifier), default=0)
        levels[identifier] = level
        row = rows.get(level, 0)
        rows[level] = row + 1
        positions[identifier] = (30 + level * 270, 100 + row * 110)
    width = max(640, (max(levels.values(), default=0) + 1) * 270 + 30)
    height = max(260, max(rows.values(), default=0) * 110 + 160)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
             f'<title>{escape(project.title)} — UnitTrace snapshot</title>',
             f'<rect width="{width}" height="{height}" fill="#f8fafc"/>',
             f'<text x="30" y="35" font-family="sans-serif" font-size="20">{escape(project.title)}</text>',
             '<text x="30" y="64" font-family="sans-serif" font-size="13">ok · warning · error · blocked | rectangle: variable · rounded: formula</text>']
    for source, target in report.edges:
        x1, y1 = positions[source]
        x2, y2 = positions[target]
        parts.append(f'<path d="M{x1+230} {y1+38} L{x2} {y2+38}" stroke="#64748b" fill="none"/>')
    for node in report.nodes:
        x, y = positions[node.id]
        color = COLORS[node.status]
        parts.extend([f'<g><rect x="{x}" y="{y}" width="230" height="80" rx="{14 if node.kind == "formula" else 2}" fill="white" stroke="{color}" stroke-width="2"/>',
                      f'<text x="{x+12}" y="{y+22}" font-family="sans-serif" font-size="14">{escape(node.id)} · {node.status}</text>',
                      f'<text x="{x+12}" y="{y+43}" font-family="sans-serif" font-size="12">{escape(labels[node.id])}</text>',
                      f'<text x="{x+12}" y="{y+65}" font-family="monospace" font-size="12">{escape(node.quantity.roundtrip + " " + node.quantity.unit if node.quantity else "No quantity")}</text></g>'])
    parts.append('</svg>')
    return ''.join(parts)


def render_html(project: Project, report: EvaluationReport) -> str:
    _current(project, report)
    labels = {n.id: n.label for n in (*project.variables, *project.formulas)}
    sections = []
    for node in report.nodes:
        # Native details/summary provides offline keyboard interaction with no script,
        # embedded executable JSON, external resource, or browser computation.
        content = json.dumps(node.to_json(), ensure_ascii=False, indent=2, allow_nan=False)
        sections.append(f'<details><summary>{escape(node.id)} — {escape(labels[node.id])} · {node.status}</summary>'
                        f'<pre>{escape(content)}</pre></details>')
    profile = escape(json.dumps(report.profile.to_json(), ensure_ascii=False, indent=2))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">'
            f'<title>{escape(project.title)} · UnitTrace snapshot</title>'
            '<style>body{font:16px/1.6 system-ui,sans-serif;color:#172b4d;background:#f8fafc;margin:auto;padding:24px;max-width:1100px}h1{overflow-wrap:anywhere}section{overflow:auto}svg{display:block}details{background:white;border:1px solid #cbd5e1;border-radius:8px;margin:12px 0;padding:12px}summary{cursor:pointer;padding:8px;min-height:28px}summary:focus-visible{outline:3px solid #1d4ed8}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}code{overflow-wrap:anywhere}</style>'
            '</head><body><p>UNITTRACE / SAVED REPORT</p>'
            f'<h1>{escape(project.title)}</h1>'
            '<p>This is an offline snapshot. Open each node for its symbolic expression, substitution, quantity, conversion factors and operation spans. '
            'To edit or recompute, import the JSON project into a running UnitTrace service or CLI.</p>'
            '<p>Ranges are supplied by the user. Dimensional consistency does not prove a physical model correct.</p>'
            f'<p>Project SHA256: <code>{report.project_hash}</code></p>'
            f'<section aria-label="Calculation graph">{render_svg(project, report)}</section>'
            '<h2>Node explanations</h2>' + ''.join(sections) +
            f'<h2>Engine profile</h2><pre>{profile}</pre></body></html>')
