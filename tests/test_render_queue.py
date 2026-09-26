import json
import subprocess
import unittest
from unittest.mock import patch

from ae_bridge import AEBridge
from ae2claude_mcp.capabilities import method_descriptor


class RenderQueueTests(unittest.TestCase):
    def evaluate(self, method, setup, *args, **kwargs):
        bridge = AEBridge.__new__(AEBridge)
        with patch.object(bridge, 'run_jsx', return_value='[]') as run:
            getattr(bridge, method)(*args, **kwargs)
        code = run.call_args.args[0]
        runner = '''const vm=require('node:vm');const ctx={};
vm.createContext(ctx);vm.runInContext(JSON.parse(process.argv[1]),ctx);
let result,error;try{result=vm.runInContext(JSON.parse(process.argv[2]),ctx)}catch(e){error=e.message}
console.log(JSON.stringify({result,error,events:ctx.events}));'''
        result = subprocess.run(['node', '-e', runner, json.dumps(setup), json.dumps(code)],
                                capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def start(self, rendering=False, queued=True, supported=True):
        setup = '''var events=[];var RQItemStatus={QUEUED:1};
var rq={rendering:RENDERING,numItems:1,item:function(){return {status:STATUS}},
render:function(){throw Error('blocking render must never run')}};
var app={project:{renderQueue:rq}};'''.replace('RENDERING', json.dumps(rendering)).replace('STATUS', '1' if queued else '0')
        if supported:
            setup += 'rq.renderAsync=function(){events.push("start")};'
        return self.evaluate('start_render', setup)

    def test_async_start_does_not_claim_completion(self):
        self.assertEqual(self.start(), {'result':'render_started', 'events':['start']})

    def test_duplicate_and_empty_queue_are_not_started(self):
        self.assertEqual(self.start(rendering=True), {'result':'already_rendering','events':[]})
        self.assertEqual(self.start(queued=False), {'result':'nothing_queued','events':[]})

    def test_unsupported_never_falls_back_to_blocking(self):
        result = self.start(supported=False)
        self.assertIn('async_render_unavailable', result['error'])
        self.assertEqual(result['events'], [])

    def test_output_escaping_template_order_and_reference_refresh(self):
        setup = '''var events=[];var old={applyTemplate:function(t){events.push(t)}};
var current={setSettings:function(s){events.push(s['Output File Info']['Full Flat Path'])}};var calls=0;
var ri={outputModule:function(){return ++calls===1?old:current}};
var app={project:{renderQueue:{rendering:false,item:function(){return ri}}}};
function File(p){this.path=p}'''
        result = self.evaluate('set_render_output', setup, 1, 'C:/测试/a"b.mp4', 'a"b\\c')
        self.assertEqual(result, {'result':'ok','events':['a"b\\c','C:/测试/a"b.mp4']})

    def test_failed_add_removes_only_new_item(self):
        setup = '''var events=[];function CompItem(){};var c=new CompItem();
var ri={outputModule:function(){return {applyTemplate:function(){throw Error('bad template')}}},
remove:function(){events.push('rollback')}};
var app={project:{activeItem:c,renderQueue:{rendering:false,items:{add:function(){return ri}}}}};'''
        self.assertEqual(self.evaluate('add_to_render_queue', setup, template='missing'),
                         {'error':'bad template','events':['rollback']})

    def test_non_comp_selection_does_not_create_item(self):
        result = self.evaluate('add_to_render_queue', 'var events=[];function CompItem(){};var app={project:{activeItem:{}}};')
        self.assertEqual(result, {'result':'no_comp','events':[]})

    def test_invalid_queue_response_is_not_empty_success(self):
        ae = AEBridge.__new__(AEBridge)
        for response in ['bad json', '{}']:
            with self.subTest(response=response), patch.object(ae, 'run_jsx', return_value=response):
                with self.assertRaises(ValueError):
                    ae.render_queue_info()

    def test_invalid_index_fails_before_bridge(self):
        ae = AEBridge.__new__(AEBridge)
        for index in [0, -1, True, '1);bad()', 1.5]:
            with self.subTest(index=index), patch.object(ae, 'run_jsx') as run:
                with self.assertRaises(ValueError):
                    ae.set_render_output(index, 'a.mp4')
                run.assert_not_called()

    def test_render_status_is_read_only(self):
        self.assertEqual(method_descriptor('get_render_status')['risk'], 'read')


if __name__ == '__main__':
    unittest.main()
