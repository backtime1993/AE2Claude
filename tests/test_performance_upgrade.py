import http.client
import io
import json
import subprocess
import threading
import unittest
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ae2claude_server as native
from ae_bridge import AEBridge
from ae_native_protocol import normalize_request
from ae2claude_mcp import server
from ae2claude_mcp.runtime import classify_bridge_method
from ae2claude_mcp.runtime import SafetyError


class NativeWriteUpgradeTests(unittest.TestCase):
    def test_ease_requires_native_fractions_unique_indices_and_finite_values(self):
        valid = {'layer_id': 2, 'path': ['ADBE Transform Group', 'ADBE Opacity'],
                 'keyframes': [{'index': 0, 'temporal_ease': [[0, .66, 0, .66]]}]}
        self.assertTrue(normalize_request('set_keyframe_ease', valid)['dry_run'])
        for frame in [{'index': True, 'temporal_ease': [[0,.5,0,.5]]},
                      {'index': 0, 'temporal_ease': [[0,66,0,66]]},
                      {'index': 0, 'temporal_ease': [[float('nan'),.5,0,.5]]},
                      {'index': 0, 'temporal_ease': [[0,.5,0]]}]:
            with self.subTest(frame=frame), self.assertRaises(ValueError):
                normalize_request('set_keyframe_ease', dict(valid, keyframes=[frame]))
        with self.assertRaises(ValueError):
            normalize_request('set_keyframe_ease', dict(valid, keyframes=valid['keyframes']*2))

    def test_layer_controls_allowlist_and_duplicate_preflight(self):
        good = {'changes': [{'layer_id': 2, 'flags': {'shy': True}, 'blend_mode': 'screen'}]}
        self.assertTrue(normalize_request('set_layer_controls', good)['dry_run'])
        for change in [{'layer_id': 2}, {'layer_id': 2, 'flags': {'locked': False}},
                       {'layer_id': 2, 'flags': {'shy': 1}}, {'layer_id': 2, 'blend_mode': 'bogus'},
                       {'layer_id': False, 'blend_mode': 'normal'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_request('set_layer_controls', {'changes': [change]})
        with self.assertRaises(ValueError):
            normalize_request('set_layer_controls', {'changes': good['changes']*2})

    def test_new_writes_obey_readonly_and_dryrun_policy(self):
        for fn, args in [(server.ae_set_native_keyframe_ease, (2,['opacity'],[])),
                         (server.ae_set_native_layer_controls, ([],))]:
            with patch.dict(os.environ, {'AE2CLAUDE_APPROVAL_MODE':'readonly'}), patch.object(server,'require_enabled'), patch.object(server,'bridge') as bridge:
                fn(*args, dry_run=True)
                bridge.reset_mock()
                with self.assertRaises(SafetyError):
                    fn(*args, dry_run=False, confirm=True)
                bridge.assert_not_called()

    def test_loaded_capabilities_are_actual_native_exports(self):
        with patch.object(native, 'psc', SimpleNamespace(native_snapshot=lambda:None, native_set_layer_controls=lambda:None)):
            self.assertEqual(native._health_payload()['features']['nativeOperations'], ['snapshot','set_layer_controls'])

    def test_cep_guard_and_body_limit(self):
        script = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert'), {EventEmitter}=require('events');
const ctx={Buffer};vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
const api=ctx.AeLocalHttp;
const request=(headers={})=>({headers:{host:'127.0.0.1:8891',...headers},rawHeaders:['Host','127.0.0.1:8891']});
assert(api.trusted(request(),8891));
for(const headers of [{origin:''},{origin:'null'},{'sec-fetch-site':'same-origin'},{host:'evil.test:8891'}]) assert(!api.trusted(request(headers),8891));
const dup=request();dup.rawHeaders.push('Host','127.0.0.1:8891');assert(!api.trusted(dup,8891));
(async()=>{
 let req=new EventEmitter(), p=api.readBody(req,8);req.emit('data',Buffer.from('{"a":1}'));req.emit('end');assert.equal((await p).a,1);
 req=new EventEmitter();p=api.readBody(req,8);req.emit('data',Buffer.from('123456789'));req.emit('end');await assert.rejects(p,/request_too_large/);
 req=new EventEmitter();p=api.readBody(req,8);req.emit('data',Buffer.from('null'));req.emit('end');await assert.rejects(p,/body_must_be_object/);
 req=new EventEmitter();p=api.readBody(req,8);req.emit('aborted');await assert.rejects(p,/request_aborted/);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        guard = Path(__file__).resolve().parents[1] / 'extensions/pin-clicker/client/local-http-guard.js'
        result = subprocess.run(['node','-e',script,str(guard)], capture_output=True, text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class LocalOriginTests(unittest.TestCase):
    def setUp(self):
        self.http = native._AEHTTPServer(('127.0.0.1', 0), native._AEHandler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.worker.join(2)

    def request(self, method='POST', headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=2)
        try:
            conn.request(method, '/exec' if method == 'POST' else '/health', b'6*7' if method == 'POST' else None, headers or {})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_browser_simple_posts_and_rebinding_cannot_execute(self):
        for headers in [{'Origin':'https://attacker.invalid'}, {'Origin':'null'},
                        {'Origin':f'http://127.0.0.1:{self.http.server_port}'},
                        {'Sec-Fetch-Site':'cross-site'}, {'Sec-Fetch-Site':'none'},
                        {'Host':f'rebind.invalid:{self.http.server_port}'}]:
            with self.subTest(headers=headers), patch.object(native, '_execute_code') as execute:
                status, result = self.request(headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(result['outcome'], 'not_started')
                execute.assert_not_called()

    def test_browser_cannot_read_project_health(self):
        self.assertEqual(self.request('GET', {'Origin':'null'})[0], 403)

    def test_native_clients_work_without_cors_headers(self):
        with patch.object(native, '_execute_code', return_value={'ok':True,'result':'42'}) as execute:
            self.assertEqual(self.request(), (200, {'ok':True,'result':'42'}))
            execute.assert_called_once_with('6*7')

    def test_transfer_encoding_is_rejected_before_execution(self):
        with patch.object(native, '_execute_code') as execute:
            self.assertEqual(self.request(headers={'Transfer-Encoding':'chunked'})[0],400)
            execute.assert_not_called()

    def test_duplicate_host_and_content_length_are_rejected(self):
        for duplicate, expected in [('Host',403), ('Content-Length',400)]:
            with self.subTest(header=duplicate), patch.object(native,'_execute_code') as execute:
                conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=2)
                try:
                    conn.putrequest('POST','/exec')
                    conn.putheader('Content-Length','3')
                    conn.putheader(duplicate, '3' if duplicate=='Content-Length' else 'localhost')
                    conn.endheaders(b'6*7')
                    response=conn.getresponse();response.read()
                    self.assertEqual(response.status,expected)
                    execute.assert_not_called()
                finally: conn.close()


class BoundedReadTests(unittest.TestCase):
    def evaluate(self, method, *args, noncomp=False):
        ae=AEBridge.__new__(AEBridge)
        with patch.object(ae,'run_jsx',return_value='{}') as call:
            getattr(ae,method)(*args)
        source=call.call_args.args[0]
        setup='''const vm=require('node:vm');const visits=[];function CompItem(){}
const c=new CompItem();Object.assign(c,{id:7,name:'comp',width:640,height:360,frameDuration:1/30,
duration:10,numLayers:100000,layer(i){visits.push(i);return {id:i,name:'layer'+i,startTime:0,outPoint:10,label:1}}});
const app={project:{numItems:4,file:null,activeItem:NONCOMP?{}:c}};
const result=JSON.parse(vm.runInNewContext(JSON.parse(process.argv[1]),{app,CompItem}));
console.log(JSON.stringify({result,visits}));'''.replace('NONCOMP','true' if noncomp else 'false')
        run=subprocess.run(['node','-e',setup,json.dumps(source)],check=True,capture_output=True,text=True,encoding='utf-8')
        return json.loads(run.stdout)

    def test_pagination_reads_only_requested_rows(self):
        data=self.evaluate('get_layer_page',10000,4)
        self.assertEqual(data['visits'],[10001,10002,10003,10004])
        self.assertEqual(data['result']['total'],100000)

    def test_overview_bounds_traversal_and_returns_total(self):
        data=self.evaluate('get_overview',3)
        self.assertEqual(data['visits'],[1,2,3])
        self.assertTrue(data['result']['truncated'])
        self.assertEqual(data['result']['layerCount'],100000)

    def test_noncomp_selection_and_out_of_range_page_are_empty(self):
        self.assertEqual(self.evaluate('get_overview',3,noncomp=True)['result']['comp'],None)
        self.assertEqual(self.evaluate('get_layer_page',100001,4)['visits'],[])

    def test_mcp_uses_single_snapshot_not_three_reads(self):
        with patch.object(server,'bridge') as bridge:
            ae=bridge.return_value.__enter__.return_value
            ae.get_overview.return_value={'ok':True}
            self.assertEqual(server.ae_overview(),{'ok':True})
            ae.get_overview.assert_called_once_with(40)
            ae.project_info.assert_not_called();ae.comp_info.assert_not_called();ae.list_layers.assert_not_called()

    def test_modern_jsx_skips_cep_watchdog_but_legacy_keeps_it(self):
        for modern in [True,False]:
            ae=AEBridge.__new__(AEBridge);ae._base_url='http://127.0.0.1:8089'
            ae.health={'features':{'wrapsJsxErrors':modern}}
            with patch.object(ae,'_arm_script_dialog_watchdog',return_value=None) as arm, patch('ae_bridge._local_urlopen',return_value=io.BytesIO(b'{"ok":true,"result":"42"}')):
                self.assertEqual(ae.run_jsx('6*7'),'42')
                self.assertEqual(arm.call_count,0 if modern else 1)


class ExtendedNativeTests(unittest.TestCase):
    props=[{'layer_id':1,'path':['ADBE Transform Group','ADBE Opacity']}]

    def test_batch_bounds_and_strict_property_schema(self):
        self.assertEqual(len(normalize_request('sample_properties',{'properties':self.props*2,'times':[0]*2048})['times']),2048)
        for props,times in [(self.props*3,[0]*2048),(self.props*65,[0]),([], [0]),
                            ([{'layer_id':True,'path':['x']}],[0]),([{'layer_id':1,'path':['x'],'extra':1}],[0])]:
            with self.subTest(properties=len(props)),self.assertRaises(ValueError):
                normalize_request('sample_properties',{'properties':props,'times':times})

    def test_inventory_validation_and_readonly_classification(self):
        self.assertEqual(normalize_request('footage_inventory',{}),{'offset':0,'max_items':500,'include_proxy':True})
        for args in [{'offset':-1},{'offset':100001},{'max_items':2001},{'include_proxy':1},{'comp_id':1}]:
            with self.subTest(args=args),self.assertRaises(ValueError): normalize_request('footage_inventory',args)
        for method in ['get_native_footage_inventory','sample_native_properties','get_overview','get_layer_page']:
            self.assertEqual(classify_bridge_method(method),'read')

    def test_allowlist_calls_new_native_functions_once(self):
        for op,args,fn in [('sample_properties',{'properties':self.props,'times':[0]},'native_sample_properties'),
                           ('footage_inventory',{},'native_footage_inventory')]:
            calls=[]
            def run(**kw): calls.append(kw);return {'ok':True,'dispatches':1}
            with patch.object(native,'psc',SimpleNamespace(**{fn:run})):
                self.assertTrue(native._execute_native({'operation':op,'arguments':args})['ok'])
            self.assertEqual(len(calls),1)


if __name__=='__main__': unittest.main()
