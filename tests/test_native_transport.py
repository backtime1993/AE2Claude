import http.client
import json
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ae2claude_server as server
from ae_bridge import AEBridge


class NativeTransportTests(unittest.TestCase):
    def setUp(self):
        self.http = server._AEHTTPServer(('127.0.0.1', 0), server._AEHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=2)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_health_remains_live_and_writes_are_rejected_while_busy(self):
        entered, release = threading.Event(), threading.Event()
        def execute(*args):
            entered.set()
            self.assertTrue(release.wait(3))
            return '42'
        results = []
        with patch.object(server, 'app', SimpleNamespace(executeScript=execute)):
            worker = threading.Thread(target=lambda: results.append(self.request('POST', '/jsx', b'6*7')))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                status, health = self.request('GET', '/health')
                self.assertEqual(status, 200)
                self.assertTrue(health['execution']['busy'])
                self.assertLess(time.monotonic() - started, 1)
                for endpoint in ('/jsx', '/exec'):
                    _, busy = self.request('POST', endpoint, b'1')
                    self.assertEqual((busy['kind'], busy['outcome']), ('busy', 'not_started'))
            finally:
                release.set()
                worker.join(3)
        self.assertTrue(results[0][1]['ok'])
        self.assertFalse(self.request('GET', '/health')[1]['execution']['busy'])

    def test_unknown_routes_and_oversized_requests_never_execute(self):
        with patch.object(server, '_execute_code') as execute:
            self.assertEqual(self.request('POST', '/typo', b'1')[0], 404)
            self.assertEqual(self.request('POST', '/exec', headers={'Content-Length': '2097153'})[0], 413)
            self.assertEqual(self.request('POST', '/exec', b'\xff')[0], 400)
            execute.assert_not_called()

    def test_native_deadline_forwarding_and_legacy_compatibility(self):
        from unittest.mock import Mock
        app = Mock()
        app.executeScript.return_value = '42'
        with patch.object(server, 'app', app), patch.object(server, 'psc', SimpleNamespace(bridgeDiagnostics=lambda: {})):
            self.assertTrue(server._execute_jsx('6*7', 600000)['ok'])
            self.assertEqual(app.executeScript.call_args.args[1], 600000)
            app.reset_mock()
            self.assertEqual(server._execute_jsx('6*7', 0)['outcome'], 'not_started')
            app.executeScript.assert_not_called()
        with patch.object(server, 'app', app), patch.object(server, 'psc', None):
            server._execute_jsx('6*7')
            self.assertEqual(len(app.executeScript.call_args.args), 1)

    def test_unknown_native_failure_is_not_retry_safe(self):
        def fail(*args): raise RuntimeError('native failure after side effect')
        with patch.object(server, 'app', SimpleNamespace(executeScript=fail)):
            result = server._execute_jsx('x')
        self.assertEqual(result['outcome'], 'unknown')
        self.assertFalse(result['retrySafe'])

    def test_client_skips_duplicate_guard_only_after_feature_negotiation(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"ok": true, "result": "42"}'
        bridge = AEBridge.__new__(AEBridge)
        bridge._base_url = 'http://127.0.0.1:8089'
        bridge.health = {'features': {'wrapsJsxErrors': True}}
        with patch.object(bridge, '_arm_script_dialog_watchdog'), patch('ae_bridge._local_urlopen', return_value=Response()) as request:
            self.assertEqual(bridge.run_jsx('6*7', timeout=2345), '42')
            self.assertEqual(request.call_args.args[0].data, b'6*7')
            self.assertEqual(request.call_args.args[0].get_header('X-ae-timeout-ms'), '2345')

    def test_import_is_inert_and_heavy_modules_are_lazy(self):
        script = ('import sys; import ae2claude_server as s; import ae2claude_mcp.server; '
                  'assert not any(s._TRANSPORT_STATE.values()); '
                  'assert "PIL.Image" not in sys.modules; assert "sqlite3" not in sys.modules')
        subprocess.run([sys.executable, '-c', script], check=True, capture_output=True)

    def test_expression_validation_rejects_unbounded_input(self):
        bridge = AEBridge.__new__(AEBridge)
        for kwargs in ({'max_properties': 0}, {'max_properties': 100001}, {'max_errors': 0}, {'time_seconds': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                bridge.validate_expressions(**kwargs)
