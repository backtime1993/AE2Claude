import json
import subprocess
import unittest
from unittest.mock import patch
from ae_bridge import AEBridge, JSXExecutionError, _wrap_jsx_for_structured_errors
from ae2claude_server import _wrap_jsx_for_structured_errors as server_wrap
import ae2claude_server
from types import SimpleNamespace


class ErrorHookTests(unittest.TestCase):
    def evaluate(self, code):
        js = """const vm=require('node:vm');let events=[];
const context={JSON:undefined,app:{beginSuppressDialogs(){events.push('begin')},endSuppressDialogs(v){events.push(v)}}};
let result=vm.runInNewContext(JSON.parse(process.argv[1]),context);
console.log(JSON.stringify({result,events}));"""
        r = subprocess.run(['node', '-e', js, json.dumps(_wrap_jsx_for_structured_errors(code))], capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(r.stdout)

    def test_missing_json_runtime_error_preserves_original(self):
        r = self.evaluate('throw new Error("probe\\n\\\"\\\\中文")')
        error = json.loads(r['result'])
        self.assertEqual(error['__ae2claude_error__'], 'Error: probe\n"\\中文')
        self.assertEqual(r['events'], ['begin', False])

    def test_syntax_error_is_caught_and_dialog_handling_restored(self):
        r = self.evaluate('var broken = ( ;')
        self.assertEqual(json.loads(r['result'])['name'], 'SyntaxError')
        self.assertEqual(r['events'], ['begin', False])

    def test_success_preserves_result_and_restores_dialog_handling(self):
        r = self.evaluate('6*7')
        self.assertEqual(r, {'result': 42, 'events': ['begin', False]})

    def test_json_query_without_optional_host_json(self):
        result = self.evaluate('JSON.stringify({values:JSON.parse("[1,null,true]"),text:"中文"})')
        self.assertEqual(json.loads(result['result']), {'values':[1,None,True],'text':'中文'})
        self.assertEqual(result['events'], ['begin', False])

    def test_native_modal_rejection_preserves_safe_retry_metadata(self):
        stub = SimpleNamespace(executeScript=lambda code: json.dumps({'__jsx_error__':'host_modal_dialog','outcome':'not_started','retrySafe':True}))
        with patch.object(ae2claude_server,'app',stub), patch.object(ae2claude_server,'psc',None):
            result=ae2claude_server._execute_jsx('app.project.numItems')
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'],'host_modal_dialog')
        self.assertEqual(result['outcome'],'not_started')
        self.assertTrue(result['retrySafe'])

    def test_client_server_guards_match(self):
        self.assertEqual(server_wrap('x'), _wrap_jsx_for_structured_errors('x'))

    def test_client_catches_guard_result_from_old_server_without_watchdog(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps({'ok':True,'result':json.dumps({'__ae2claude_error__':'original','name':'Error'})}).encode()
        ae = AEBridge.__new__(AEBridge)
        ae._base_url = 'http://127.0.0.1:8089'
        with patch.object(ae,'_arm_script_dialog_watchdog',return_value=None), patch('ae_bridge._local_urlopen',return_value=Response()) as request:
            with self.assertRaises(JSXExecutionError) as caught: ae.run_jsx('throw new Error("original")')
            self.assertEqual(caught.exception.payload['error'],'original')
            self.assertIn(b'beginSuppressDialogs',request.call_args.args[0].data)


if __name__ == '__main__': unittest.main()
