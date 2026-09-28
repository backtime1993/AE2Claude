"""Live batch integrity regressions; use only an empty acceptance project."""
import json
import os
import unittest

from ae_bridge import AEBridge
from ae2claude_mcp.agent_runtime import execute_batch


@unittest.skipUnless(os.environ.get('AE2CLAUDE_LIVE_TEST') == '1', 'requires an isolated running AE')
class LiveBatchIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.ae=AEBridge()
        self.addCleanup(self.ae.close)
        state=self.read('({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null,dirty:app.project.dirty,version:app.version})')
        if state['items'] or state['file'] or state['dirty']:
            self.skipTest('requires an empty, unsaved, clean acceptance project')
        self.assertTrue(state['version'].startswith(os.environ.get('AE2CLAUDE_EXPECTED_AE_MAJOR','27')+'.'))
        self.addCleanup(self.ae.run_jsx,'app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();"clean"')
        self.ae.create_comp('batch integrity',320,180,30,3)
        self.ae.add_solid('target',[.4,.3,.2],80,60)
        self.layer=self.read('app.project.activeItem.layer("target").id')
        self.opacity=['ADBE Transform Group','ADBE Opacity']

    def read(self,expr):
        return json.loads(self.ae.run_jsx('JSON.stringify('+expr+')'))

    def opacity_value(self):
        return self.read('app.project.activeItem.layer("target").opacity.value')

    def test_jsx_invalid_later_path_prevents_earlier_write(self):
        result=self.ae.property_batch(self.layer,[{'action':'set','path':self.opacity,'value':12},
            {'action':'set','path':['missing property'],'value':5}],backend='jsx')
        self.assertFalse(result['ok'])
        self.assertEqual(self.opacity_value(),100,result)
        self.assertTrue(all(not r['ok'] for r in result['results']),result)

    def test_jsx_dry_run_rejects_incorrect_dimensions(self):
        result=self.ae.property_batch(self.layer,[{'action':'set','path':self.opacity,'value':[10,20]}],backend='jsx',dry_run=True)
        self.assertFalse(result['ok'],result)
        self.assertEqual(self.opacity_value(),100)

    def test_jsx_group_is_not_a_value_property(self):
        result=self.ae.property_batch(self.layer,[{'action':'get','path':['ADBE Transform Group']}],backend='jsx',dry_run=True)
        self.assertFalse(result['ok'],result)

    def test_jsx_static_set_on_animated_property_is_preflighted(self):
        self.ae.set_keyframes('target','opacity',[(0,80),(1,60)])
        result=self.ae.property_batch(self.layer,[{'action':'set','path':self.opacity,'value':12},
            {'action':'set','path':['ADBE Transform Group','ADBE Rotate Z'],'value':40}],backend='jsx')
        self.assertFalse(result['ok'],result)
        self.assertTrue(all(not r['ok'] for r in result['results']),result)
        self.assertEqual(self.read('app.project.activeItem.layer("target").rotation.value'),0)

    def test_native_preflight_does_not_report_unexecuted_write_as_success(self):
        result=self.ae.property_batch(self.layer,[{'action':'set','path':self.opacity,'value':12},
            {'action':'set','path':['missing property'],'value':5}],backend='native')
        self.assertFalse(result['ok'])
        self.assertEqual(self.opacity_value(),100)
        self.assertTrue(all(not r['ok'] for r in result['results']),result)

    def test_workflow_batch_stops_on_structured_failure(self):
        result=execute_batch([
            {'method':'property_batch','args':[self.layer,[{'action':'get','path':['missing property']}]],'kwargs':{'backend':'jsx'}},
            {'method':'set_value','args':['target','opacity',12]}],confirm=True)
        self.assertFalse(result['ok'],result)
        self.assertEqual(result['completedCount'],1,result)
        self.assertEqual(self.opacity_value(),100,result)

    def test_boolean_layer_index_never_selects_layer_one(self):
        with self.assertRaises(ValueError):
            self.ae.property_batch({'index':True},[{'action':'set','path':self.opacity,'value':12}],backend='jsx')
        self.assertEqual(self.opacity_value(),100)

    def test_fractional_layer_index_never_rounds_to_layer_one(self):
        with self.assertRaises(ValueError):
            self.ae.property_batch({'index':1.9},[{'action':'set','path':self.opacity,'value':12}],backend='jsx')
        self.assertEqual(self.opacity_value(),100)

    def test_invalid_shape_path_leaves_no_empty_group(self):
        self.ae.add_shape_layer('shape')
        before=self.read('app.project.activeItem.layer("shape").property("ADBE Root Vectors Group").numProperties')
        with self.assertRaises((ValueError,RuntimeError)):
            self.ae.add_shape_path('shape',[[0,0],[20,0],[0,20]],in_tangents=[[0,0]])
        after=self.read('app.project.activeItem.layer("shape").property("ADBE Root Vectors Group").numProperties')
        self.assertEqual(after,before)

    def test_fail_fast_false_reports_failure_and_applies_valid_operation(self):
        result=self.ae.property_batch(self.layer,[{'action':'set','path':['missing property'],'value':5},
            {'action':'set','path':self.opacity,'value':12}],backend='jsx',fail_fast=False)
        self.assertFalse(result['ok'])
        self.assertFalse(result['results'][0]['ok'])
        self.assertTrue(result['results'][1]['ok'])
        self.assertEqual(self.opacity_value(),12)


    def test_mcp_call_propagates_structured_failure(self):
        from ae2claude_mcp.server import ae_call
        result=ae_call('property_batch',[self.layer,[{'action':'get','path':['missing property']}]],{'backend':'jsx'},confirm=True)
        self.assertFalse(result['ok'],result)
        self.assertFalse(result['result']['ok'])

    def test_unicode_separator_names_work_in_batch_and_inspection(self):
        name='name\u2028line\u2029end'
        self.ae.rename_layer('target',name)
        result=self.ae.property_batch(name,[{'action':'set','path':self.opacity,'value':34}],backend='jsx',undo_name=name)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.read('app.project.activeItem.layer(1).opacity.value'),34)
        inspected=self.ae.inspect_properties(name,backend='jsx')
        self.assertTrue(inspected['ok'],inspected)
        self.assertGreater(inspected['count'],0)

    def test_valid_curve_keeps_tangents_and_open_state(self):
        self.ae.add_shape_layer('shape')
        vertices=[[0,0],[20,0],[0,20]]
        incoming=[[-2,0],[-3,0],[0,-4]]
        outgoing=[[2,0],[3,0],[0,4]]
        self.ae.add_shape_path('shape',vertices,incoming,outgoing,False)
        result=self.read('(function(){var s=app.project.activeItem.layer("shape").property("ADBE Root Vectors Group").property(1).property("ADBE Vectors Group").property(1).property("ADBE Vector Shape").value;return {v:s.vertices,i:s.inTangents,o:s.outTangents,c:s.closed};})()')
        self.assertEqual(result,{'v':vertices,'i':incoming,'o':outgoing,'c':False})

    def test_text_batch_preserves_style_and_updates_text(self):
        self.ae.add_text_layer('before','text')
        before=self.read('app.project.activeItem.layer("text").property("ADBE Text Properties").property("ADBE Text Document").value.fontSize')
        result=self.ae.property_batch('text',[{'action':'set','path':['ADBE Text Properties','ADBE Text Document'],'value':'after'}],backend='jsx')
        self.assertTrue(result['ok'],result)
        doc=self.read('(function(){var d=app.project.activeItem.layer("text").property("ADBE Text Properties").property("ADBE Text Document").value;return {text:d.text,size:d.fontSize};})()')
        self.assertEqual(doc,{'text':'after','size':before})


    def test_jsx_layer_control_remains_writable(self):
        self.ae.add_solid('reference',[.1,.2,.3],80,60)
        self.ae.add_effect_by_match_name('target','ADBE Layer Control')
        index=self.read('app.project.activeItem.layer("reference").index')
        path=['ADBE Effect Parade',0,'ADBE Layer Control-0001']
        result=self.ae.property_batch('target',[{'action':'set','path':path,'value':index}],backend='jsx')
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.read('app.project.activeItem.layer("target").property("ADBE Effect Parade").property(1).property(1).value'),index)
