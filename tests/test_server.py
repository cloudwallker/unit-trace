"""Real loopback requests exercise the session and bounded resource contract."""

import http.client
import json
import socket
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import unittest

from tests.test_engine import project


class RunningServer(unittest.TestCase):
    def setUp(self):
        from unit_trace.server import make_server
        self.server = make_server()
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.port = int(self.server.origin.rsplit(':', 1)[1])

    def tearDown(self):
        self.server.close()
        self.thread.join(6)
        self.assertFalse(self.thread.is_alive())

    def request(self, path, data=None, method=None, headers=None):
        method = method or ('POST' if data is not None else 'GET')
        base = {'Origin': self.server.origin, 'X-Unit-Trace-Session': self.server.session_token}
        if data is not None:
            base['Content-Type'] = 'application/json'
        if headers:
            for k, v in headers.items():
                if v is None:
                    base.pop(k, None)
                else:
                    base[k] = v
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=7)
        try:
            connection.request(method, path, json.dumps(data).encode() if data is not None else None, base)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def raw(self, request):
        with socket.create_connection(('127.0.0.1', self.port), timeout=7) as connection:
            connection.sendall(request.encode('ascii'))
            chunks = []
            while chunk := connection.recv(65536):
                chunks.append(chunk)
            return b''.join(chunks)


class SessionTests(RunningServer):
    def test_valid_session_and_security_headers(self):
        status, headers, body = self.request('/api/profile')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['id'], 'unit-trace-scalar-v1')
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_origin_host_token_and_fetch_site_rejected(self):
        data = {'project': project([], []).to_json(), 'revision': 0}
        for headers in ({'Origin': None}, {'Origin': 'https://example.invalid'},
                        {'Host': 'localhost:' + str(self.port)},
                        {'X-Unit-Trace-Session': None}, {'X-Unit-Trace-Session': 'wrong'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=list(headers)):
                status, _, body = self.request('/api/evaluate', data, headers=headers)
                self.assertEqual(status, 403)
                self.assertIn('errors', json.loads(body))
                self.assertNotIn(self.server.session_token.encode(), body)
        self.assertEqual(self.request('/api/profile', headers={'Origin': 'https://example.invalid'})[0], 403)
        self.assertEqual(self.request('/api/profile', headers={'Origin': None})[0], 200)

    def test_routes_do_not_offer_files_or_traversal(self):
        for path in ('/missing', '/api/files', '/api/read?path=secret', '/../pyproject.toml',
                     '/%2e%2e/pyproject.toml', '/web/app.js', '/app.js?file=secret'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        for path in ('/', '/app.js', '/graph.js', '/style.css'):
            self.assertEqual(self.request(path)[0], 200)

    def test_protocol_boundaries_are_checked_before_reading(self):
        head = (f'POST /api/evaluate HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                f'Origin: {self.server.origin}\r\nX-Unit-Trace-Session: {self.server.session_token}\r\n')
        cases = [
            ('Content-Length: 262145\r\nContent-Type: application/json\r\n', 413),
            ('Content-Length: 2\r\nContent-Type: text/plain\r\n', 415),
            ('Transfer-Encoding: chunked\r\nContent-Type: application/json\r\n', 400),
            ('Content-Length: 2\r\nContent-Length: 2\r\nContent-Type: application/json\r\n', 400),
            ('Content-Length: -1\r\nContent-Type: application/json\r\n', 400),
            ('Content-Length: 2\r\nContent-Type: application/json\r\nContent-Encoding: gzip\r\n', 400),
            ('Content-Type: application/json\r\n', 400),
            (f'Content-Length: 2\r\nContent-Type: application/json\r\nOrigin: {self.server.origin}\r\n', 400),
        ]
        for headers, expected in cases:
            with self.subTest(expected=expected, headers=headers.split(':')[0]):
                raw = self.raw(head + headers + '\r\n{}')
                self.assertEqual(int(raw.split(b' ', 2)[1]), expected)
        self.assertEqual(self.request('/api/evaluate', {'unknown': 1})[0], 422)

    def test_four_slow_connections_limit_the_fifth_and_close_cleans_up(self):
        connections = []
        try:
            for _ in range(4):
                c = socket.create_connection(('127.0.0.1', self.port), timeout=2)
                c.sendall(b'POST /api/evaluate HTTP/1.1\r\n')
                connections.append(c)
            time.sleep(.15)
            self.assertEqual(self.request('/api/profile')[0], 503)
            # Busy admission must deliver its response even with unread inbound
            # bytes; closing such a Winsock connection can reset the response.
            for _ in range(3):
                self.assertEqual(self.request('/api/evaluate', {'padding': 'x' * 32768})[0], 503)
            started = time.monotonic()
            self.server.close()
            self.server.close()
            self.server.shutdown()
            self.thread.join(6)
            self.assertLess(time.monotonic() - started, 6)
            self.assertFalse(self.thread.is_alive())
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', self.port), timeout=.2)
        finally:
            for c in connections:
                c.close()

    def test_request_deadline_applies_to_incomplete_headers(self):
        started = time.monotonic()
        raw = self.raw('POST /api/evaluate HTTP/1.1\r\n')
        self.assertLess(time.monotonic() - started, 6)
        self.assertNotIn(b'200 OK', raw)

    def test_invalid_json_is_400(self):
        head = (f'POST /api/evaluate HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                f'Origin: {self.server.origin}\r\nX-Unit-Trace-Session: {self.server.session_token}\r\n'
                'Content-Type: application/json\r\n')
        for body in ('{', '{"revision":0,"revision":1}'):
            raw = self.raw(head + f'Content-Length: {len(body)}\r\n\r\n' + body)
            self.assertEqual(int(raw.split(b' ', 2)[1]), 400)

    def test_non_ascii_session_is_403(self):
        self.assertEqual(self.request('/api/profile', headers={'X-Unit-Trace-Session': '\u00e9'})[0], 403)

    def test_close_before_serving_is_idempotent(self):
        from unit_trace.server import make_server
        unused = make_server()
        started = time.monotonic()
        unused.shutdown()
        unused.close()
        unused.close()
        self.assertLess(time.monotonic() - started, 1)


class ApiTests(RunningServer):
    def test_evaluate_echoes_revision_and_real_dimension_errors(self):
        p = project([('length', '2', 'cm'), ('time', '1', 's')],
                    [('bad', 'length + time', None), ('child', 'bad * 2', None)])
        status, _, body = self.request('/api/evaluate', {'project': p.to_json(), 'revision': 42})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['revision'], 42)
        from unit_trace.engine import evaluate_project
        self.assertEqual(data['report'], evaluate_project(p).to_json())
        self.assertEqual(data['report']['firstError']['code'], 'dimension_mismatch')
        self.assertEqual(data['report']['nodes'][-1]['status'], 'blocked')

    def test_structure_errors_and_revision_are_not_successful_reports(self):
        p = project([], [('bad', 'unknown * 2', None)]).to_json()
        self.assertEqual(self.request('/api/evaluate', {'project': p, 'revision': 0})[0], 422)
        for rev in (True, -1, 2147483648, '1'):
            self.assertEqual(self.request('/api/evaluate', {'project': project([], []).to_json(), 'revision': rev})[0], 422)

    def test_previous_project_drives_removed_and_affected_nodes(self):
        previous = project([('x', '2', 'm'), ('y', '3', 'm')],
                           [('area', 'x*y', 'm**2'), ('old', 'area*2', None)])
        current = project([('x', '4', 'm'), ('y', '3', 'm')], [('area', 'x**2', 'm**2')])
        status, _, body = self.request('/api/evaluate', {'project': current.to_json(),
                                      'previousProject': previous.to_json(), 'revision': 3})
        self.assertEqual(status, 200)
        report = json.loads(body)['report']
        self.assertEqual(report['removedIds'], ['old'])
        self.assertEqual(report['affectedIds'], ['x', 'area'])

    def test_zero_conversion_keeps_independent_factor(self):
        status, _, body = self.request('/api/convert', {'value': '0', 'fromUnit': 'cm', 'toUnit': 'm'})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data['quantity']['value'], 0)
        self.assertEqual(data['conversion']['factor'], .01)
        self.assertEqual(data['conversion']['toUnit'], 'm')

    def test_export_recomputes_with_fixed_filenames(self):
        p = project([('length', '2', 'cm')], [('double', 'length*2', 'm')]).to_json()
        for kind, mime in (('json', 'application/json'), ('svg', 'image/svg+xml'), ('html', 'text/html')):
            status, headers, body = self.request('/api/export', {'project': p, 'format': kind})
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith(mime))
            self.assertEqual(headers['Content-Disposition'], f'attachment; filename="unit-trace.{kind}"')
            self.assertNotIn(self.server.session_token.encode(), body)
            if kind == 'json':
                self.assertEqual(json.loads(body)['report']['nodes'][-1]['quantity']['value'], .04)

    def test_templates_are_exactly_the_eight_packaged_experiments(self):
        status, _, body = self.request('/api/templates')
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual({x['id'] for x in data['templates']},
                         {'flow', 'density', 'spring', 'electric', 'energy', 'diffusion', 'concentration', 'pendulum'})
        for item in data['templates']:
            self.assertEqual(set(item['variants']), {'normal', 'dimension', 'scale'})


class LifecycleTests(unittest.TestCase):
    def test_close_during_serving_thread_startup_cannot_deadlock(self):
        # Delay the standard-library boundary, retaining its real implementation,
        # to make the otherwise scheduler-dependent start/close interleaving exact.
        script = '''import threading, time
from http.server import HTTPServer
from unit_trace.server import make_server
entered=threading.Event()
original=HTTPServer.serve_forever
def delayed(self, *args, **kwargs):
    entered.set()
    time.sleep(.15)
    return original(self, *args, **kwargs)
HTTPServer.serve_forever=delayed
s=make_server()
t=threading.Thread(target=s.serve_forever)
t.start()
assert entered.wait(2)
s.close()
t.join(1)
assert not t.is_alive()
print('closed during startup')
'''
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'src')}
        process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=environment)
        try:
            try:
                out, err = process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                self.fail('close() deadlocked while the serving thread started')
            self.assertEqual(process.returncode, 0, err)
            self.assertIn(b'closed during startup', out)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_owned_subprocesses_release_slow_connections_on_close_and_cancel(self):
        source = str(Path(__file__).parents[1] / 'src')
        environment = {**os.environ, 'PYTHONPATH': source}
        helper = '''import sys, threading
from unit_trace.server import make_server
s=make_server()
t=threading.Thread(target=s.serve_forever)
t.start()
print(s.origin, flush=True)
try:
    sys.stdin.readline()
finally:
    s.close()
    t.join(6)
print('workers=' + str(sum(t.name.startswith('unit-trace') for t in threading.enumerate())), flush=True)
'''
        for cancel in (False, True):
            with self.subTest(cancel=cancel):
                command = [sys.executable, '-u', '-m', 'unit_trace', 'serve'] if cancel else [sys.executable, '-u', '-c', helper]
                options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {}
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, env=environment, **options)
                connection = None
                try:
                    line = process.stdout.readline().decode().strip()
                    port = int(line.rsplit(':', 1)[1])
                    connection = socket.create_connection(('127.0.0.1', port), timeout=2)
                    connection.sendall(b'POST /api/evaluate HTTP/1.1\r\n')
                    time.sleep(.1)
                    started = time.monotonic()
                    if cancel:
                        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
                        out, err = process.communicate(timeout=6)
                    else:
                        out, err = process.communicate(b'close\n', timeout=6)
                    self.assertLess(time.monotonic() - started, 6)
                    self.assertEqual(process.returncode, 3 if cancel else 0, err)
                    if not cancel:
                        self.assertIn(b'workers=0', out)
                    self.assertNotIn(b'Traceback', err)
                    with self.assertRaises(OSError):
                        socket.create_connection(('127.0.0.1', port), timeout=.2)
                finally:
                    if connection:
                        connection.close()
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=6)
