import ctypes
import http.client
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ae2claude_server as server
from ae_bridge import AEBridge


class PythonExecutionReviewTests(unittest.TestCase):
    def test_runtime_syntax_error_does_not_replay_expression(self):
        calls = []
        def mutate_then_fail():
            calls.append('mutation')
            raise SyntaxError('runtime parser failure')
        with patch.dict(server._BASE_GLOBALS, {'mutate_then_fail': mutate_then_fail}):
            result = server._execute_code('mutate_then_fail()')
        self.assertEqual(calls, ['mutation'])
        self.assertFalse(result['ok'])
        self.assertIn('runtime parser failure', result['error'])

    def test_statement_fallback_and_expression_results_still_work(self):
        self.assertEqual(server._execute_code('6 * 7'), {'ok': True, 'result': '42'})
        self.assertEqual(server._execute_code('_result = 6 * 7'), {'ok': True, 'result': '42'})
        self.assertEqual(server._execute_code('_result = 7', prefer_exec=True), {'ok': True, 'result': '7'})

    def test_failing_result_repr_returns_error_and_releases_busy_gate(self):
        class BadResult:
            def __repr__(self):
                raise ValueError('result formatting failed after execution')
        with patch.dict(server._BASE_GLOBALS, {'bad_result': BadResult()}):
            result = server._execute_code('bad_result')
        self.assertFalse(result['ok'])
        self.assertIn('result formatting failed', result['error'])
        self.assertNotEqual(result.get('outcome'), 'not_started')
        self.assertFalse(server._EXECUTION_LOCK.locked())
        self.assertEqual(server._execute_code('21 * 2')['result'], '42')

    def test_http_repr_failure_does_not_claim_operation_never_started(self):
        class BadResult:
            def __repr__(self):
                raise ValueError('formatting failed after mutation')
        calls = []
        def mutate():
            calls.append('mutation')
            return BadResult()
        http_server = server._AEHTTPServer(('127.0.0.1', 0), server._AEHandler)
        thread = threading.Thread(target=http_server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(server._BASE_GLOBALS, {'mutate': mutate}):
                conn = http.client.HTTPConnection('127.0.0.1', http_server.server_port, timeout=3)
                try:
                    conn.request('POST', '/exec', b'mutate()')
                    response = conn.getresponse()
                    result = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertFalse(result['ok'])
                    self.assertNotEqual(result.get('outcome'), 'not_started')
                finally:
                    conn.close()
            self.assertEqual(calls, ['mutation'])
        finally:
            http_server.shutdown()
            http_server.server_close()
            thread.join(2)


class DialogScopeReviewTests(unittest.TestCase):
    def test_no_ae_process_never_enumerates_or_dismisses_other_apps(self):
        bridge = AEBridge.__new__(AEBridge)
        bridge._dismiss_running = True
        user32 = Mock()
        def enum_windows(*args):
            bridge._dismiss_running = False
        user32.EnumWindows.side_effect = enum_windows
        with patch('ae_bridge.sys.platform', 'win32'), patch.object(bridge, '_find_ae_pid', return_value=0), \
             patch.object(ctypes, 'windll', SimpleNamespace(user32=user32), create=True), \
             patch.object(ctypes, 'WINFUNCTYPE', return_value=lambda fn: fn, create=True), \
             patch('ae_bridge.time.sleep'):
            bridge._dialog_dismisser_loop()
        user32.EnumWindows.assert_not_called()
        user32.PostMessageW.assert_not_called()
        self.assertFalse(bridge._dismiss_running)

    def test_pid_lookup_matches_executable_instead_of_window_title(self):
        with patch('ae_bridge.subprocess.run', return_value=SimpleNamespace(stdout='1234\n')) as run:
            self.assertEqual(AEBridge._find_ae_pid(), 1234)
        command = run.call_args.args[0][-1]
        self.assertIn('Get-Process -Name AfterFX', command)
        self.assertNotIn('MainWindowTitle', command)


class PythonResultRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.http = server._AEHTTPServer(('127.0.0.1', 0), server._AEHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.ae = AEBridge.__new__(AEBridge)
        self.ae._base_url = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)

    def test_python_string_results_preserve_quotes_backslashes_and_unicode(self):
        samples = ["'quoted'", '"quoted"', 'both \' and " quotes',
                   'F:\\work\\shots\\clip.aep', 'first\nsecond\tcolumn', '人物/衣襟', '']
        for expected in samples:
            with self.subTest(value=expected):
                self.assertEqual(self.ae._run_py('_result = ' + repr(expected)), expected)

    def test_json_properties_round_trip_without_an_extra_escape_layer(self):
        expected = {'layer': "Character's outline", 'path': 'F:\\work\\素材.psd',
                    'expression': 'value + "quote"\n// more'}
        payload = json.dumps(expected, ensure_ascii=False)
        result = self.ae._run_py('_result = ' + repr(payload))
        self.assertEqual(json.loads(result), expected)

    def test_non_string_result_representations_keep_the_existing_contract(self):
        self.assertEqual(self.ae._run_py('_result = 42'), '42')
        self.assertEqual(self.ae._run_py('_result = [1, 2]'), '[1, 2]')
        self.assertEqual(self.ae._run_py('_result = None'), '')


class NativeColorBindingReviewTests(unittest.TestCase):
    def test_background_color_rejects_short_vectors_before_sdk_dispatch(self):
        # Compile the production binding against a minimal host stub: exercising
        # invalid input must never require launching or crashing After Effects.
        from pathlib import Path
        import re
        import shutil
        import subprocess
        import tempfile
        import ae_bridge

        compiler = shutil.which('g++') or shutil.which('clang++')
        if not compiler:
            self.skipTest('C++17 compiler unavailable')
        root = Path(ae_bridge.__file__).resolve().parent
        source = (root / 'src/PyShiftAE/CoreLib/PyCore.cpp').read_text(encoding='utf-8')
        binding = re.search(
            r'\.def_property\("bgColor", &CompItem::getBGColor,\s*'
            r'(\[\]\(CompItem& self, std::vector<float> c\)\s*\{.*?\})\)', source, re.S)
        self.assertIsNotNone(binding)
        program = r'''
#include <cassert>
#include <stdexcept>
#include <vector>
struct CompItem {
    int calls = 0;
    std::vector<float> last;
    void setBGColor(float r, float g, float b) { ++calls; last = {r,g,b}; }
};
int main() {
    auto setter = SETTER;
    CompItem comp;
    for (int size=0; size<3; ++size) {
        bool rejected=false;
        try { setter(comp,std::vector<float>(size,0.5f)); }
        catch(const std::invalid_argument&) { rejected=true; }
        assert(rejected && comp.calls==0);
    }
    setter(comp,{0.1f,0.2f,0.3f});
    assert((comp.last==std::vector<float>{0.1f,0.2f,0.3f}));
    setter(comp,{0.4f,0.5f,0.6f,1.0f});
    assert((comp.last==std::vector<float>{0.4f,0.5f,0.6f}));
    assert(comp.calls==2);
}
'''.replace('SETTER', binding.group(1))
        with tempfile.TemporaryDirectory(prefix='ae2claude-color-test-') as directory:
            cpp = Path(directory) / 'binding.cpp'
            exe = Path(directory) / 'binding-test.exe'
            cpp.write_text(program, encoding='utf-8')
            compiled = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                       '-D_GLIBCXX_ASSERTIONS', str(cpp), '-o', str(exe)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(executed.returncode, 0, executed.stderr)


class BetaProcessReviewTests(unittest.TestCase):
    def test_beta_executable_is_included_in_process_lookup(self):
        def process_query(command, **kwargs):
            script = command[-1]
            return SimpleNamespace(stdout='4321\n' if "'AfterFX (Beta)'" in script else '')
        with patch('ae_bridge.subprocess.run', side_effect=process_query):
            self.assertEqual(AEBridge._find_ae_pid(), 4321)
