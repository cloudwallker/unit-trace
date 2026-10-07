"""Bounded, session-protected loopback service with one resource owner."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
import json
import secrets
import socket
import threading
import time

from .engine import convert_input, evaluate_project
from .exports import render_html, render_svg
from .models import CalculationError, Conversion, Issue, ProjectValidationError, input_error
from .profile import get_profile
from .serialization import serialize_bundle
from .units import conversion_factor
from .validation import load_json, parse_project

TEMPLATE_IDS = ('flow', 'density', 'spring', 'electric', 'energy', 'diffusion', 'concentration', 'pendulum')
STATIC = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
          '/graph.js': ('graph.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"


def templates() -> dict:
    root = files('unit_trace').joinpath('templates')
    return {'templates': [{'id': identifier, 'variants': {
        variant: load_json(root.joinpath(identifier, variant + '.json').read_bytes())
        for variant in ('normal', 'dimension', 'scale')}} for identifier in TEMPLATE_IDS]}


class UnitTraceServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, port: int):
        super().__init__(('127.0.0.1', port), _Handler)
        self.origin = f'http://127.0.0.1:{self.server_address[1]}'
        self.session_token = secrets.token_hex(32)
        self._workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix='unit-trace')
        self._guard = threading.RLock()
        self._active = {}
        self._running = False
        self._closed = False
        self._stopping = threading.Event()
        self._serve_thread = None

    def serve_forever(self, poll_interval=.05):
        with self._guard:
            if self._closed or self._stopping.is_set():
                return
            self._running = True
            self._serve_thread = threading.get_ident()
        try:
            super().serve_forever(poll_interval=poll_interval)
        finally:
            with self._guard:
                self._running = False
                self._serve_thread = None

    def process_request(self, request, client_address):
        with self._guard:
            if self._stopping.is_set() or len(self._active) >= 4:
                try:
                    body = b'{"errors":[{"id":"busy","code":"limit_exceeded","field":"$","message":"Service is busy or closing.","relatedIds":[]}]}'
                    request.settimeout(.1)
                    request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\nCache-Control: no-store\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
                    self._drain_after_response(request)
                except OSError:
                    pass
                finally:
                    self.shutdown_request(request)
                return
            request.settimeout(5)
            self._active[request] = time.monotonic() + 5
            self._workers.submit(self._finish, request, client_address)

    def _finish(self, request, address):
        try:
            self.finish_request(request, address)
        except (OSError, ValueError):
            pass
        finally:
            self._drain_after_response(request)
            self.shutdown_request(request)
            with self._guard:
                self._active.pop(request, None)

    @staticmethod
    def _drain_after_response(request):
        # This applies to every early rejection, including 403 before body read.
        # Closing an unread Winsock queue can reset bytes already sent. Half-close
        # exposes response EOF immediately; draining remains time/byte bounded.
        try:
            request.shutdown(socket.SHUT_WR)
            deadline = time.monotonic() + .05
            remaining = 262144
            while remaining > 0 and time.monotonic() < deadline:
                request.settimeout(max(.001, deadline - time.monotonic()))
                chunk = request.recv(min(16384, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    @staticmethod
    def _interrupt(connection):
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def service_actions(self):
        with self._guard:
            expired = [s for s, deadline in self._active.items() if deadline <= time.monotonic()]
        for connection in expired:
            self._interrupt(connection)

    def shutdown(self):
        self._stopping.set()
        with self._guard:
            running = self._running
            same_thread = self._serve_thread == threading.get_ident()
        if running:
            if same_thread:
                raise RuntimeError('Shutdown must be coordinated outside the serving thread.')
            super().shutdown()

    def close(self):
        with self._guard:
            if self._closed:
                return
            self._closed = True
            self._stopping.set()
            connections = list(self._active)
        for connection in connections:
            self._interrupt(connection)
        self.shutdown()
        self.server_close()
        self._workers.shutdown(wait=True, cancel_futures=True)
        with self._guard:
            self._active.clear()
            self.session_token = ''


def make_server(port: int = 0) -> UnitTraceServer:
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid loopback port.')
    return UnitTraceServer(port)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def send_error(self, code, message=None, explain=None):
        self._error(code, 'invalid_schema', 'Invalid HTTP request.')

    def _send(self, status, body, mime='application/json', filename=None):
        if self.server._stopping.is_set():
            return
        try:
            self.send_response(status)
            self.send_header('Content-Type', mime + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if filename:
                self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass
        finally:
            self.close_connection = True

    def _json(self, status, data):
        self._send(status, json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))

    def _error(self, status, code, message):
        self._json(status, {'errors': [Issue(code, code, '$', message).to_json()]})

    def _check(self, write=False):
        for name in ('Host', 'Origin', 'X-Unit-Trace-Session', 'Content-Length', 'Content-Type', 'Transfer-Encoding', 'Content-Encoding', 'Sec-Fetch-Site'):
            if len(self.headers.get_all(name, [])) > 1:
                self._error(400, 'invalid_schema', 'Duplicate request header.')
                return False
        if self.headers.get('Host') != self.server.origin.removeprefix('http://'):
            self._error(403, 'invalid_schema', 'Invalid request origin or session.')
            return False
        origin = self.headers.get('Origin')
        if (write and origin != self.server.origin) or (origin is not None and origin != self.server.origin) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._error(403, 'invalid_schema', 'Invalid request origin or session.')
            return False
        if self.path.startswith('/api/') and not secrets.compare_digest(self.headers.get('X-Unit-Trace-Session', '').encode('utf-8'), self.server.session_token.encode('ascii')):
            self._error(403, 'invalid_schema', 'Invalid request origin or session.')
            return False
        return True

    def do_GET(self):
        if not self._check():
            return
        if self.path in STATIC:
            name, mime = STATIC[self.path]
            body = files('unit_trace').joinpath('web', name).read_bytes()
            if self.path == '/':
                body = body.replace(b'__SESSION_TOKEN__', self.server.session_token.encode('ascii'))
            self._send(200, body, mime)
        elif self.path == '/api/profile':
            self._json(200, get_profile().to_json())
        elif self.path == '/api/templates':
            self._json(200, templates())
        else:
            self._error(404, 'invalid_schema', 'Unknown resource.')

    def do_POST(self):
        if not self._check(write=True):
            return
        if self.path not in ('/api/evaluate', '/api/convert', '/api/export'):
            self._error(404, 'invalid_schema', 'Unknown resource.')
            return
        if self.headers.get('Transfer-Encoding') is not None or self.headers.get('Content-Encoding') is not None:
            self._error(400, 'invalid_schema', 'Encoded request bodies are unsupported.')
            return
        length = self.headers.get('Content-Length', '')
        if not length.isascii() or not length.isdecimal() or len(length) > 10:
            self._error(400, 'invalid_schema', 'A valid Content-Length is required.')
            return
        length = int(length)
        if length > 262144:
            self._error(413, 'limit_exceeded', 'Request exceeds 256 KiB.')
            return
        if self.headers.get_content_type() != 'application/json':
            self._error(415, 'invalid_schema', 'Content-Type must be application/json.')
            return
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._error(400, 'invalid_schema', 'Incomplete request body.')
                return
            try:
                data = load_json(raw, max_bytes=262144)
            except ProjectValidationError as exc:
                self._json(400, {'errors': [issue.to_json() for issue in exc.issues]})
                return
            self._dispatch(data)
        except ProjectValidationError as exc:
            self._json(422, {'errors': [issue.to_json() for issue in exc.issues]})
        except CalculationError as exc:
            self._json(422, {'errors': [exc.issue.to_json()]})
        except (OSError, TimeoutError):
            self._error(400, 'invalid_schema', 'Request could not be read.')

    def _dispatch(self, data):
        allowed = {'/api/evaluate': ({'project', 'revision'}, {'previousProject'}),
                   '/api/convert': ({'value', 'fromUnit', 'toUnit'}, set()),
                   '/api/export': ({'project', 'format'}, set())}
        required, optional = allowed[self.path]
        if not isinstance(data, dict) or not required <= data.keys() or not data.keys() <= required | optional:
            raise input_error('invalid_schema', '$', 'Missing or unknown request fields.')
        if self.path == '/api/evaluate':
            revision = data['revision']
            if type(revision) is not int or not 0 <= revision <= 2147483647:
                raise input_error('invalid_schema', 'revision', 'Revision must be a bounded integer.')
            previous = parse_project(data['previousProject']) if 'previousProject' in data else None
            report = evaluate_project(parse_project(data['project']), previous)
            self._json(200, {'revision': revision, 'report': report.to_json()})
        elif self.path == '/api/convert':
            q = convert_input(data['value'], data['fromUnit'], data['toUnit'])
            factor = conversion_factor(data['fromUnit'], data['toUnit'])
            self._json(200, {'quantity': q.to_json(), 'conversion': Conversion('input', data['fromUnit'], data['toUnit'], factor).to_json()})
        else:
            if data['format'] not in ('json', 'svg', 'html'):
                raise input_error('invalid_schema', 'format', 'Unsupported export format.')
            project = parse_project(data['project'])
            report = evaluate_project(project)
            kind = data['format']
            if kind == 'json':
                body, mime = serialize_bundle(project, report), 'application/json'
            else:
                body = (render_svg if kind == 'svg' else render_html)(project, report).encode('utf-8')
                mime = 'image/svg+xml' if kind == 'svg' else 'text/html'
            self._send(200, body, mime, 'unit-trace.' + kind)
