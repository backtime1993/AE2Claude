import json
import os
import subprocess
import unittest
from unittest.mock import patch

from ae2claude_mcp.production import JSX, normalize, invoke
from ae2claude_mcp import server
from ae2claude_mcp.runtime import SafetyError


class ProductionTests(unittest.TestCase):
    def test_unsigned_stable_ids_and_newlines(self):
        cfg=normalize('text_range',{'comp_id':3966343632,'layer':1,'start':0,'end':1,'text':'A\r\nB\nC'},True)
        self.assertEqual(cfg['compId'],3966343632)
        self.assertEqual(cfg['text'],'A\rB\rC')
        cfg=normalize('project_items',{'changes':[{'item_id':3966343632,'folder_id':3966343633}]},True)
        self.assertEqual(cfg['changes'][0]['item_id'],3966343632)

    def test_null_shape_arguments_reject_before_transport(self):
        for op,key in [('rename','name'),('add','match_name')]:
            with self.subTest(op=op),self.assertRaises(ValueError):
                normalize('shape_operator',{'layer':1,'path':[0],'operation':op,key:None},False)

    def test_bounded_tree_is_prefix_not_skipped_first_children(self):
        setup='''var events=[];function CompItem(){};var c=new CompItem();
var PropertyType={INDEXED_GROUP:1};
var group={name:'Contents',matchName:'ADBE Root Vectors Group',propertyType:1,numProperties:4,
property:function(i){return {name:'Child'+i,matchName:'shape',numProperties:0,value:i}}};
var layer={id:1,property:function(){return group}};c.numLayers=1;c.layer=function(){return layer};var app={project:{activeItem:c}};'''
        out=self.evaluate('shape_contents',{'layer':1,'max_nodes':3},setup)['result']
        self.assertTrue(out['truncated'])
        self.assertEqual([x['name'] for x in out['result']],['Contents','Child1','Child2'])

    def test_timed_essential_property_reads_requested_time(self):
        setup='''var events=[];function CompItem(){};var c=new CompItem();
var PropertyType={PROPERTY:1},p={propertyType:1,numKeys:1,expressionEnabled:false,value:0,
setValueAtTime:function(t,v){events.push([t,v])},valueAtTime:function(t){return t===0.5?100:0}};
var l={id:1,essentialProperty:{property:function(){return p}}};c.numLayers=1;c.layer=function(){return l};
var app={project:{activeItem:c},beginUndoGroup:function(){},endUndoGroup:function(){}};'''
        out=self.evaluate('essential_property',{'layer':1,'path':[0],'time':0.5,'value':100},setup,False)['result']
        self.assertEqual(out['result']['value'],100)
        self.assertEqual(out['result']['time'],0.5)

    def test_valid_parent_child_reverse_avoids_intermediate_cycle(self):
        setup='''var events=[];function FolderItem(id,name,parent){this.id=id;this.name=name;this._parent=parent}
Object.defineProperty(FolderItem.prototype,'parentFolder',{get:function(){return this._parent},set:function(p){var x=p;while(x){if(x===this)throw Error('cycle');x=x._parent}this._parent=p;events.push([this.id,p.id])}});
var root=new FolderItem(0,'root',null),a=new FolderItem(1,'A',root),b=new FolderItem(2,'B',a);
var app={project:{rootFolder:root,numItems:2,item:function(i){return [a,b][i-1]}},beginUndoGroup:function(){},endUndoGroup:function(){}};'''
        out=self.evaluate('project_items',{'changes':[{'item_id':1,'folder_id':2},{'item_id':2,'folder_id':0}]},setup,False)['result']
        self.assertTrue(out['ok'],out)
        self.assertEqual([x['parentId'] for x in out['result']],[2,0])

    def render_host(self, disk=(), queued=()):
        return '''var events=[],disk=DISK,queued=QUEUED;var $={os:'Windows'};
function CompItem(){};var c=new CompItem();c.id=1;c.name='Clip';
function File(path){this.fsName=path;this.exists=disk.indexOf(path)>=0;this.name=path.split('/').pop();
this.parent={exists:true,fsName:'C:/out',getFiles:function(){return disk.map(function(p){return new File(p)})}}}
function output(path){return {file:new File(path),setSettings:function(s){this.file=new File(s['Output File Info']['Full Flat Path'].replace(/\\.mov$/,'.mp4'))}}}
var items=queued.map(function(p){var om=output(p);return {render:true,numOutputModules:1,outputModule:function(){return om}}});
var rq={rendering:false,item:function(i){return items[i-1]},items:{add:function(){events.push('add');var om=output('C:/out/Clip.mp4');var ri={render:true,numOutputModules:1,outputModule:function(){return om},remove:function(){items.splice(items.indexOf(ri),1);events.push('remove-new')}};items.push(ri);return ri}}};
Object.defineProperty(rq,'numItems',{get:function(){return items.length}});
var app={project:{activeItem:c,file:{parent:{fsName:'C:/out'}},renderQueue:rq},beginUndoGroup:function(){},endUndoGroup:function(){}};
'''.replace('DISK',json.dumps(disk)).replace('QUEUED',json.dumps(queued))

    def test_pending_output_collision_rejected_after_template_extension(self):
        out=self.evaluate('render_output',{'output_path':'C:/out/Clip.mov'},self.render_host(queued=['C:/out/clip.mp4']),False)
        self.assertFalse(out['result']['ok'],out)
        self.assertIn('render_output_reserved',out['result']['error'])
        self.assertEqual(out['events'],['add','remove-new'])

    def test_default_path_avoids_actual_extension_and_queue_collisions(self):
        for disk,queued in [(['C:/out/Clip.mp4'],[]),([],['C:/out/clip.mp4'])]:
            with self.subTest(disk=disk,queued=queued):
                out=self.evaluate('render_output',{},self.render_host(disk,queued),False)['result']
                self.assertTrue(out['ok'],out)
                self.assertEqual(out['result']['path'],'C:/out/Clip_1.mp4')

    def test_sequence_existing_frames_rejected(self):
        out=self.evaluate('render_output',{'output_path':'C:/out/frame_[#####].png'},self.render_host(disk=['C:/out/frame_00001.png']),False)
        self.assertFalse(out['result']['ok'],out)
        self.assertIn('render_destination_exists',out['result']['error'])
        self.assertEqual(out['events'],[])

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
