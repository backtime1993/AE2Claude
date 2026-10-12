import json
import os
import subprocess
import unittest
from unittest.mock import patch

from ae2claude_mcp.production import JSX, normalize, invoke
from ae2claude_mcp import server
from ae2claude_mcp.runtime import SafetyError


class ProductionTests(unittest.TestCase):
    def evaluate(self, action, options, setup, dry_run=True):
        code = JSX.replace('SETTINGS', json.dumps(normalize(action, options, dry_run)))
        runner = '''const vm=require('node:vm'),fs=require('fs');
const [setup,code]=JSON.parse(fs.readFileSync(0,'utf8'));const ctx={};vm.createContext(ctx);
vm.runInContext(setup,ctx);const result=JSON.parse(vm.runInContext(code,ctx));
console.log(JSON.stringify({result,events:ctx.events}));'''
        run = subprocess.run(['node', '-e', runner], input=json.dumps([setup, code]),
                             capture_output=True, text=True, check=True)
        return json.loads(run.stdout)

    def test_reject_invalid_inputs_before_transport(self):
        rows = [('unknown', {}), ('text_range', {'layer':1,'start':2,'end':1,'text':'a'}),
                ('text_range', {'layer':1,'start':0,'end':1,'text':'a','arbitrary':True}),
                ('stroke_dashes', {'layer':1,'path':[0],'dashes':[float('nan')]}),
                ('keyframe_interpolation', {'layer':1,'path':['Opacity'],'key_indices':[True],'in_type':'hold'}),
                ('keyframe_interpolation', {'layer':1,'path':['Opacity'],'key_indices':[0],'in_type':'linear','temporal_auto_bezier':True}),
                ('project_items', {'changes':[{'item_id':1,'name':'A'},{'item_id':1,'name':'B'}]}),
                ('render_output', {'overwrite':'yes'})]
        for action, options in rows:
            with self.subTest(action=action), self.assertRaises(ValueError):
                normalize(action, options, True)

    def test_explicit_shape_root_and_unicode_transport(self):
        cfg=normalize('shape_operator', {'layer':1,'path':[],'operation':'add','match_name':'ADBE Vector Group'}, True)
        self.assertEqual(cfg['path'], [])
        class Bridge:
            def run_jsx(self, code, **kwargs):
                self.code=code
                return '{"ok":true}'
        ae=Bridge()
        invoke(ae,'create_folder',{'name':'中文 " quoted \\ folder'})
        self.assertIn('\\u4e2d', ae.code)

    def test_readonly_blocks_writes_but_allows_plans(self):
        with patch.dict(os.environ, {'AE2CLAUDE_APPROVAL_MODE':'readonly'}), patch.object(server,'require_enabled'), patch.object(server,'bridge') as bridge, patch.object(server,'invoke_production',return_value={'ok':True}):
            self.assertTrue(server.ae_production('create_folder',{'name':'Test'})['ok'])
            bridge.reset_mock()
            with self.assertRaises(SafetyError):
                server.ae_production('create_folder',{'name':'Test'},dry_run=False,confirm=True)
            bridge.assert_not_called()

    def test_all_key_indices_preflight_before_writes(self):
        setup='''var events=[];function CompItem(){};var c=new CompItem();var target={numKeys:1,isInterpolationTypeValid:function(){return true},setInterpolationTypeAtKey:function(){events.push('write')}};
var l={id:10,property:function(){return target}};c.numLayers=1;c.layer=function(){return l};
var app={project:{activeItem:c},beginUndoGroup:function(){events.push('undo')},endUndoGroup:function(){}};
var KeyframeInterpolationType={LINEAR:1,BEZIER:2,HOLD:3};'''
        out=self.evaluate('keyframe_interpolation',{'layer':10,'path':['Opacity'],'key_indices':[0,2],'in_type':'hold'},setup,False)
        self.assertFalse(out['result']['ok'])
        self.assertEqual(out['result']['outcome'],'not_started')
        self.assertEqual(out['events'],[])

    def test_render_collision_does_not_create_queue_item(self):
        setup='''var events=[];function CompItem(){};var c=new CompItem();c.id=1;
function File(path){this.fsName=path;this.parent={exists:true};this.exists=true;}
var app={project:{activeItem:c,renderQueue:{rendering:false,items:{add:function(){events.push('add')}}}}};'''
        out=self.evaluate('render_output',{'output_path':'F:/exists.mov'},setup,False)
        self.assertIn('render_destination_exists',out['result']['error'])
        self.assertEqual(out['events'],[])

    def test_failed_render_template_removes_only_new_item(self):
        setup='''var events=[];function CompItem(){};var c=new CompItem();c.id=1;
function File(path){this.fsName=path;this.parent={exists:true};this.exists=false;}
var ri={applyTemplate:function(){throw Error('bad template')},remove:function(){events.push('remove-new')}};
var app={project:{activeItem:c,renderQueue:{rendering:false,items:{add:function(){events.push('add');return ri}}}},beginUndoGroup:function(){},endUndoGroup:function(){events.push('end')}};'''
        out=self.evaluate('render_output',{'output_path':'F:/new.mov','render_template':'missing'},setup,False)
        self.assertFalse(out['result']['ok'])
        self.assertEqual(out['events'],['add','remove-new','end'])

    def test_folder_cycles_fail_before_any_mutation(self):
        setup='''var events=[];function FolderItem(){};var root=new FolderItem(),a=new FolderItem(),b=new FolderItem();
root.id=0;a.id=1;b.id=2;a.name='A';b.name='B';a.parentFolder=root;b.parentFolder=root;
var app={project:{rootFolder:root,numItems:2,item:function(i){return [a,b][i-1]}},beginUndoGroup:function(){events.push('write')},endUndoGroup:function(){}};'''
        out=self.evaluate('project_items',{'changes':[{'item_id':1,'folder_id':2},{'item_id':2,'folder_id':1}]},setup,False)
        self.assertIn('folder_cycle',out['result']['error'])
        self.assertEqual(out['events'],[])


if __name__=='__main__':
    unittest.main()
