"""Explicit local file operations and a loopback-only command-line interface."""

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import webbrowser

from . import __version__
from .engine import evaluate_project
from .exports import render_html, render_svg
from .models import Issue, ProjectValidationError, input_error
from .serialization import parse_bundle, serialize_bundle
from .server import TEMPLATE_IDS, make_server, templates
from .validation import load_json


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise input_error('invalid_schema', 'arguments', 'Invalid command-line arguments. Use --help.')


def _same(a: Path, b: Path) -> bool:
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))


def _outputs(paths, source=None, overwrite=False):
    targets = [Path(p) for p in paths if p is not None]
    for index, target in enumerate(targets):
        if source is not None and _same(source, target):
            raise input_error('invalid_schema', 'output', 'Output must not replace the source input or its aliases.')
        if any(_same(target, other) for other in targets[:index]):
            raise input_error('invalid_schema', 'output', 'Each output must have a separate path.')
        if target.exists() and not overwrite:
            raise input_error('invalid_schema', 'output', 'Output exists. Use --overwrite to replace a separate output.')
        if target.is_dir():
            raise input_error('invalid_schema', 'output', 'Output must be a file.')


def _write(path, body, source=None, overwrite=False):
    target = Path(path)
    # Recheck immediately before opening; opening without truncation also lets us
    # compare the actual file identity before any byte can be changed.
    _outputs([target], source, overwrite)
    flags = os.O_WRONLY | os.O_CREAT | (0 if overwrite else os.O_EXCL) | getattr(os, 'O_BINARY', 0)
    fd = os.open(target, flags, 0o600)
    try:
        if source is not None and os.path.samestat(os.fstat(fd), source.stat()):
            raise input_error('invalid_schema', 'output', 'Output aliases the source input.')
        with os.fdopen(fd, 'wb', closefd=False) as output:
            output.truncate(0)
            output.write(body)
    finally:
        os.close(fd)


def _status(report):
    if any(node.status in ('error', 'blocked') for node in report.nodes):
        return 1
    if any(node.status == 'warning' for node in report.nodes):
        return 2
    return 0


def _cancel(*_):
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog='unit-trace', description='Trace scalar formulas, units, and dependencies locally.')
    parser.add_argument('--version', action='version', version=f'unit-trace {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve', help='Start a private loopback session.')
    serve.add_argument('--port', type=int, default=0)
    serve.add_argument('--open', action='store_true')
    evaluate = commands.add_parser('evaluate', help='Recompute a Project or JSON Bundle.')
    evaluate.add_argument('input')
    for kind in ('json', 'svg', 'html'):
        evaluate.add_argument('--' + kind)
    evaluate.add_argument('--overwrite', action='store_true')
    evaluate.add_argument('--recompute', action='store_true', help='Explicitly recompute a compatible Bundle whose engine profile differs.')
    demo = commands.add_parser('demo', help='Write an original experiment Project.')
    demo.add_argument('template', choices=TEMPLATE_IDS)
    demo.add_argument('--variant', choices=('normal', 'dimension', 'scale'), default='normal')
    demo.add_argument('--json')
    try:
        args = parser.parse_args(argv)
        if args.command == 'serve':
            server = make_server(args.port)
            old_break = None
            try:
                if hasattr(signal, 'SIGBREAK') and __import__('threading').current_thread() is __import__('threading').main_thread():
                    old_break = signal.signal(signal.SIGBREAK, _cancel)
                print(f'UnitTrace listening at {server.origin}', flush=True)
                if args.open:
                    webbrowser.open(server.origin)
                server.serve_forever()
            finally:
                server.close()
                if old_break is not None:
                    signal.signal(signal.SIGBREAK, old_break)
            return 0
        if args.command == 'demo':
            item = next(t for t in templates()['templates'] if t['id'] == args.template)
            raw = json.dumps(item['variants'][args.variant], ensure_ascii=False, indent=2).encode('utf-8') + b'\n'
            if args.json:
                _write(args.json, raw)
            else:
                sys.stdout.buffer.write(raw)
            return 0
        source = Path(args.input)
        with source.open('rb') as input_file:
            raw = input_file.read(8388609)
        loaded = parse_bundle(load_json(raw))
        if loaded.requires_recompute_confirmation and not args.recompute:
            raise input_error('engine_mismatch', 'report.profile', 'Engine profile differs. Use --recompute to explicitly evaluate with the current engine.')
        report = evaluate_project(loaded.project)
        _outputs([args.json, args.svg, args.html], source, args.overwrite)
        artifacts = []
        if args.json:
            artifacts.append((args.json, serialize_bundle(loaded.project, report)))
        if args.svg:
            artifacts.append((args.svg, render_svg(loaded.project, report).encode('utf-8')))
        if args.html:
            artifacts.append((args.html, render_html(loaded.project, report).encode('utf-8')))
        for path, body in artifacts:
            _write(path, body, source, args.overwrite)
        print(json.dumps({'projectHash': report.project_hash, 'nodes': len(report.nodes),
                          'errors': len(report.root_errors), 'warnings': sum(len(n.warnings) for n in report.nodes)}))
        return _status(report)
    except ProjectValidationError as exc:
        print(json.dumps({'errors': [i.to_json() for i in exc.issues]}), file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyboardInterrupt):
        issue = Issue('io_or_cancelled', 'invalid_schema', '$', 'Operation failed or was cancelled safely.')
        print(json.dumps({'errors': [issue.to_json()]}), file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
