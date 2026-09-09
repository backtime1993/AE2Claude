import json
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from ae_bridge import AEBridge, JSXExecutionError, _local_urlopen
from ae2claude_mcp import server


class TransportTests(unittest.TestCase):
    def test_proxy_discovery_is_skipped_and_redirects_are_not_followed(self):
        hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/replayed')
                else:
                    self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:%s' % httpd.server_port
        try:
            with patch('urllib.request.getproxies', side_effect=AssertionError('proxy lookup')):
                with _local_urlopen(urllib.request.Request(base), 1) as response:
                    self.assertEqual(response.read(), b'{}')
                with self.assertRaises(urllib.error.HTTPError):
                    _local_urlopen(urllib.request.Request(base + '/redirect'), 1)
            self.assertEqual(hits, ['/', '/redirect'])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    def test_non_loopback_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            _local_urlopen(urllib.request.Request('http://example.com'), 1)

    def test_uncertain_jsx_request_is_never_replayed(self):
        for error in (TimeoutError('timeout'), ConnectionResetError('reset'), ValueError('bad JSON')):
            ae = AEBridge.__new__(AEBridge)
            ae._base_url = 'http://127.0.0.1:8089'
            with patch.object(ae, '_arm_script_dialog_watchdog', return_value=None), patch(
                'ae_bridge._local_urlopen', side_effect=error
            ) as request:
                with self.assertRaises(JSXExecutionError) as caught:
                    ae.run_jsx('6*7')
            self.assertEqual(request.call_count, 1)
            self.assertEqual(caught.exception.payload['outcome'], 'unknown')
            self.assertFalse(caught.exception.payload['retrySafe'])

    def test_offline_then_online_in_same_client(self):
        ae = AEBridge.__new__(AEBridge)
        ae.port = 8089
        ae._base_url = 'http://127.0.0.1:8089'
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"status":"ok","bridge_version":"4.3.1"}'
        with patch('ae_bridge._local_urlopen', side_effect=[ConnectionRefusedError(), Response()]):
            with self.assertRaises(ConnectionError):
                ae.reconnect()
            ae.reconnect()
        self.assertEqual(ae.health['status'], 'ok')


class SnapshotTests(unittest.TestCase):
    def evaluate_snapshot(self, project_expression):
        ae = AEBridge.__new__(AEBridge)
        def execute(code, timeout):
            self.assertEqual(timeout, 5000)
            script = '''const vm=require('node:vm');
const app={version:'27.0x22'};
Object.defineProperty(app,'project',{get(){return PROJECT;}});
const result=vm.runInNewContext(JSON.parse(process.argv[1]),{app,JSON:undefined});
process.stdout.write(result);'''.replace('PROJECT', project_expression)
            return subprocess.run(['node', '-e', script, json.dumps(code)], check=True,
                                  capture_output=True, text=True, encoding='utf-8').stdout
        with patch.object(ae, 'run_jsx', side_effect=execute) as call:
            result = ae.get_connection_info()
        self.assertEqual(call.call_count, 1)
        return result

    def test_saved_unicode_project_without_json(self):
        result = self.evaluate_snapshot('{numItems:840,file:{fsName:"F:/中文/%20\\n工程.aep"},dirty:true}')
        self.assertTrue(result['connected'])
        self.assertTrue(result['projectReadable'])
        self.assertTrue(result['projectDirty'])
        self.assertEqual(result['project']['file'], 'F:/中文/%20\n工程.aep')

    def test_unsaved_and_missing_projects(self):
        result = self.evaluate_snapshot('{numItems:0,file:null,dirty:false}')
        self.assertEqual(result['project']['file'], 'unsaved')
        result = self.evaluate_snapshot('null')
        self.assertTrue(result['connected'])
        self.assertFalse(result['projectReadable'])

    def test_status_really_uses_one_snapshot(self):
        with patch.object(server, 'bridge') as bridge:
            ae = bridge.return_value.__enter__.return_value
            ae.get_connection_info.return_value = {'connected': True, 'projectReadable': True}
            self.assertTrue(server.ae_ping()['ok'])
            ae.get_connection_info.assert_called_once()
            ae.project_info.assert_not_called()
            ae.run_jsx.assert_not_called()


if __name__ == '__main__':
    unittest.main()
