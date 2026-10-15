"""Executable regressions for authoring selection, reports and anchor positioning."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

from ae_bridge import AEBridge
from ae2claude_mcp.properties import property_batch, inspect_properties
from ae2claude_mcp.skill_reports import PREFLIGHT_JSX


def evaluate(setup, code, expression="({})"):
    runner = """const vm=require('node:vm'),fs=require('node:fs');
const [setup,code,expression]=JSON.parse(fs.readFileSync(0,'utf8'));
const ctx={};vm.createContext(ctx);vm.runInContext(setup,ctx);
let result, error;try{result=vm.runInContext(code,ctx)}catch(e){error=String(e)}
console.log(JSON.stringify({result,error,state:vm.runInContext(expression,ctx)}));"""
    run = subprocess.run(["node", "-e", runner], input=json.dumps([setup, code, expression]),
                         capture_output=True, text=True, check=True, timeout=10)
    return json.loads(run.stdout)


class CapturingBridge:
    timeout = 1

    def run_jsx(self, code, **kwargs):
        self.code = code
        return '{}'


@unittest.skipUnless(shutil.which("node"), "requires Node for JSX execution")
class ProductionReviewTests(unittest.TestCase):
    def test_property_jsx_rejects_ambiguous_layer_before_write(self):
        setup = '''var events=[];function CompItem(){};var c=new CompItem();
var prop={propertyType:1,propertyValueType:1,canVaryOverTime:true,numKeys:0,
 setValue:function(v){events.push(v)},valueAtTime:function(){return 50}};
var layers=[{name:'same',id:1,property:function(){return prop}},
 {name:'same',id:2,property:function(){return prop}}];
c.numLayers=2;c.time=0;c.layer=function(s){return typeof s==='number'?layers[s-1]:layers[0]};
var app={project:{activeItem:c},beginUndoGroup:function(){events.push('undo')},endUndoGroup:function(){}};
var PropertyType={PROPERTY:1},PropertyValueType={OneD:1};'''
        for inspect in (False, True):
            with self.subTest(inspect=inspect):
                ae = CapturingBridge()
                if inspect:
                    inspect_properties(ae, 'same', backend='jsx')
                else:
                    property_batch(ae, 'same', [{'action':'set','path':['Opacity'],'value':12}], backend='jsx')
                out = evaluate(setup, ae.code, 'events')
                self.assertEqual(out['state'], [])
                self.assertIn('ambiguous_layer_name', out.get('error', '') + out.get('result', ''))

    def test_property_native_rejects_ambiguous_layer_before_dispatch(self):
        class CompItem:
            layers = [SimpleNamespace(name='same'), SimpleNamespace(name='same')]
        class NativeBridge:
            timeout = 1
            calls = 0

            def _run_py(self, code, **kwargs):
                def dispatch(*args):
                    self.calls += 1
                    return {}
                scope = {'app':SimpleNamespace(project=SimpleNamespace(activeItem=CompItem())),
                         'psc':SimpleNamespace(agent_stream_batch=dispatch,agent_inspect_streams=dispatch)}
                exec(code, scope)
                return scope['_result']
        ae = NativeBridge()
        for inspect in (False, True):
            with self.subTest(inspect=inspect), self.assertRaisesRegex(RuntimeError, 'ambiguous_layer_name'):
                if inspect:
                    inspect_properties(ae, 'same', backend='native')
                else:
                    property_batch(ae, 'same', [{'action':'set','path':['Opacity'],'value':12}], backend='native')
        self.assertEqual(ae.calls, 0)

    def test_unique_property_name_and_stable_id_still_resolve(self):
        setup = '''var events=[];function CompItem(){};var c=new CompItem();
var prop={propertyType:1,propertyValueType:1,canVaryOverTime:true,numKeys:0,
 setValue:function(v){events.push(v)}};
var layers=[{name:'unique',id:1,property:function(){return prop}},
 {name:'second',id:2,property:function(){return prop}}];
c.numLayers=2;c.layer=function(i){return layers[i-1]};
var app={project:{activeItem:c},beginUndoGroup:function(){},endUndoGroup:function(){}};
var PropertyType={PROPERTY:1},PropertyValueType={OneD:1};'''
        for selector in ('unique', 2, {'index':2}):
            with self.subTest(selector=selector):
                ae = CapturingBridge()
                property_batch(ae, selector, [{'action':'set','path':['Opacity'],'value':12}], backend='jsx')
                out = evaluate(setup, ae.code, 'events')
                self.assertNotIn('error', out)
                self.assertEqual(out['state'], [12])

    def test_preflight_marks_unvisited_output_modules_as_truncated(self):
        setup = '''function CompItem(){};function FootageItem(){};
var ri={comp:{id:1},render:true,numOutputModules:1,outputModule:function(){return {file:{fsName:'C:/out.mov',parent:{exists:true}}}}};
var app={project:{file:null,dirty:false,numItems:0,usedFonts:[],renderQueue:{numItems:ITEMS,item:function(){return ri}}}};'''
        for count in (1, 2):
            with self.subTest(count=count):
                code = PREFLIGHT_JSX.replace('SETTINGS', json.dumps({'maxItems':1,'maxProperties':10}))
                out = json.loads(evaluate(setup.replace('ITEMS', str(count)), code)['result'])
                self.assertEqual(len(out['outputs']), 1)
                self.assertEqual(out['truncated'], count > 1)

    def test_timed_effect_write_reads_requested_time(self):
        ae = object.__new__(AEBridge)
        captured = []
        ae.run_jsx = lambda code: captured.append(code) or '{"ok":true}'
        ae.set_effect_property('layer', 1, 'gain', 75, at_time=2)
        setup = '''function CompItem(){};var c=new CompItem();var prop={matchName:'gain',name:'Gain',value:10,
 setValueAtTime:function(t,v){this.at=t;this.written=v},valueAtTime:function(t){return t===this.at?this.written:10}};
var effect={propertyIndex:1,numProperties:1,property:function(){return prop}};
c.layer=function(){return {property:function(){return {property:function(){return effect}}}}};
var app={project:{activeItem:c},beginUndoGroup:function(){},endUndoGroup:function(){}};'''
        result = json.loads(evaluate(setup, captured[0])['result'])
        self.assertEqual(result['value'], 75)

    def test_center_anchor_preserves_visual_position_and_is_idempotent(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' / 'set-anchor-point.jsx').read_text(encoding='utf-8')
        for three_d, anchor, position, scale, rotation in [
            (False,[0,0],[0,0],[100,100,100],0),
            (False,[50,50],[100,100],[100,100,100],0),
            (False,[10,20],[250,100],[150,75,100],37),
            (True,[10,20,30],[250,100,20],[150,75,200],0),
        ]:
            with self.subTest(three_d=three_d, anchor=anchor):
                setup = '''function CompItem(){};function CameraLayer(){};function LightLayer(){};
function p(v){return {value:v,isTimeVarying:false,setValue:function(x){this.value=x}}}
var layer={threeDLayer:THREE,anchorPoint:p(ANCHOR),position:p(POSITION),scale:p(SCALE),rotation:p(ROTATION),
 xRotation:p(0),yRotation:p(0),zRotation:p(0),orientation:p([0,0,0]),
 mask:{numProperties:0},sourceRectAtTime:function(){return {left:0,top:0,width:100,height:100}}};
var comp=new CompItem();comp.time=0;comp.selectedLayers=[layer];
var app={project:{activeItem:comp},beginUndoGroup:function(){},endUndoGroup:function(){}};
function origin(){var a=layer.anchorPoint.value,p=layer.position.value,s=layer.scale.value;
 var x=a[0]*s[0]/100,y=a[1]*s[1]/100,r=layer.rotation.value*Math.PI/180;
 var v=[p[0]-x*Math.cos(r)+y*Math.sin(r),p[1]-x*Math.sin(r)-y*Math.cos(r)];
 if(layer.threeDLayer)v.push(p[2]-a[2]*s[2]/100);return v;}
var before=origin();'''
                for key, value in [('THREE',three_d),('ANCHOR',anchor),('POSITION',position),('SCALE',scale),('ROTATION',rotation)]:
                    setup = setup.replace(key, json.dumps(value))
                out = evaluate(setup, script + '\n' + script,
                               '({before:before,after:origin(),anchor:layer.anchorPoint.value})')
                self.assertNotIn('error', out)
                self.assertEqual(out['state']['anchor'][:2], [50,50])
                for a,b in zip(out['state']['before'],out['state']['after']):
                    self.assertAlmostEqual(a,b)

    def test_unsupported_anchor_does_not_partially_move_layer(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' / 'set-anchor-point.jsx').read_text(encoding='utf-8')
        setup = '''function CompItem(){};function CameraLayer(){};function LightLayer(){};
var events=[],layer={anchorPoint:{numKeys:1},position:{setValue:function(){events.push('write')}}};
var comp=new CompItem();comp.selectedLayers=[layer];
var app={project:{activeItem:comp},beginUndoGroup:function(){events.push('begin')},endUndoGroup:function(){events.push('end')}};'''
        out = evaluate(setup, script, 'events')
        self.assertIn('animated_anchor_point_not_supported', out['error'])
        self.assertEqual(out['state'], ['begin','end'])

    def test_cloned_keys_keep_selection_when_source_times_overlap(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' / 'clone-keys.jsx').read_text(encoding='utf-8')
        setup = '''function CompItem(){};var keys=[{t:0,v:10,selected:true},{t:1,v:20,selected:true}];
var prop={selectedKeys:[1,2],canVaryOverTime:true,isSpatial:false,
 keyTime:function(i){return keys[i-1].t},keyValue:function(i){return keys[i-1].v},
 isInterpolationTypeValid:function(){return false},
 setValueAtTime:function(t,v){var row=keys.filter(function(x){return x.t===t})[0];
  if(row)row.v=v;else keys.push({t:t,v:v,selected:false});keys.sort(function(a,b){return a.t-b.t})},
 nearestKeyIndex:function(t){for(var i=0;i<keys.length;i++)if(keys[i].t===t)return i+1;throw Error('missing time')},
 setSelectedAtKey:function(i,v){keys[i-1].selected=v}};
var comp=new CompItem();comp.time=1;comp.selectedLayers=[{stretch:100,selectedProperties:[prop]}];
var KeyframeInterpolationType={BEZIER:1,HOLD:2,LINEAR:3};
var app={project:{activeItem:comp},beginUndoGroup:function(){},endUndoGroup:function(){}};'''
        out = evaluate(setup, script, 'keys.filter(function(x){return x.selected}).map(function(x){return x.t})')
        self.assertNotIn('error', out)
        self.assertEqual(out['state'], [1,2])


if __name__ == '__main__':
    unittest.main()
