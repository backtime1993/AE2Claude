"""Host regressions: independent JSX readback, isolated empty acceptance project."""
import json
import os
import unittest

from ae_bridge import AEBridge, _wrap_jsx_for_structured_errors


@unittest.skipUnless(os.environ.get('AE2CLAUDE_LIVE_TEST') == '1', 'requires running AE acceptance instance')
class BridgeHostRegressionTests(unittest.TestCase):
    def setUp(self):
        self.ae = AEBridge()
        self.addCleanup(self.ae.close)
        state = self.read('({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null,dirty:app.project.dirty})')
        if state['items'] or state['file'] or state['dirty']:
            self.skipTest('requires empty, unsaved, clean acceptance project')
        self.addCleanup(self.ae.run_jsx, 'app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();"clean"')
        self.ae.create_comp('regression', 320, 180, 30, 3)

    def read(self, expression):
        return json.loads(self.ae.run_jsx('JSON.stringify(' + expression + ')'))

    def solid(self, name):
        self.ae.add_solid(name, [.3,.4,.5], 64, 48)

    def test_track_matte_uses_named_nonadjacent_source(self):
        self.solid('target'); self.solid('decoy'); self.solid('wanted')
        self.ae.set_track_matte('target', 'wanted', 'alpha')
        result = self.read('(function(){var c=app.project.activeItem;var l=c.layer("target");return {actual:l.trackMatteLayer?l.trackMatteLayer.id:null,wanted:c.layer("wanted").id};})()')
        self.assertEqual(result['actual'], result['wanted'])

    def test_missing_track_matte_does_not_modify_target(self):
        self.solid('target'); self.solid('decoy')
        before = self.read('Number(app.project.activeItem.layer("target").trackMatteType)')
        try:
            self.ae.set_track_matte('target', 'missing', 'alpha')
        except (ValueError, RuntimeError):
            pass
        self.assertEqual(self.read('Number(app.project.activeItem.layer("target").trackMatteType)'), before)

    def test_precompose_false_keeps_attributes_by_name(self):
        self.check_precompose(False)

    def test_precompose_false_keeps_attributes_by_index(self):
        self.check_precompose(True)

    def check_precompose(self, by_index):
        self.solid('source')
        self.ae.set_value('source', 'opacity', 37)
        self.ae.set_value('source', 'position', [91,67])
        comp_id = self.ae.comp_info()['id']
        expected = self.read('({opacity:app.project.activeItem.layer(1).opacity.value,position:app.project.activeItem.layer(1).position.value})')
        if by_index:
            self.ae.precompose_by_index([1], 'nested', move_attrs=False)
        else:
            self.ae.precompose(['source'], 'nested', move_attrs=False)
        row = self.read('(function(){var l=app.project.itemByID(' + str(comp_id) + ').layer(1);return {opacity:l.opacity.value,position:l.position.value};})()')
        self.assertEqual(row, expected)

    def test_missing_precompose_target_does_not_precompose_subset(self):
        self.solid('source')
        comp_id = self.ae.comp_info()['id']
        before = self.read('({items:app.project.numItems,layer:app.project.activeItem.layer(1).id})')
        try:
            self.ae.precompose(['source','missing'], 'unexpected')
        except (ValueError, RuntimeError):
            pass
        after = self.read('({items:app.project.numItems,layer:app.project.itemByID(' + str(comp_id) + ').layer(1).id})')
        self.assertEqual(after, before)

    def test_reorder_moves_to_requested_index(self):
        for name in ('bottom','middle','top'):
            self.solid(name)
        self.ae.reorder_layer('top', 3)
        self.assertEqual(self.read('app.project.activeItem.layer("top").index'), 3)
        self.ae.reorder_layer('top', 2)
        self.assertEqual(self.read('app.project.activeItem.layer("top").index'), 2)

    def test_get_value_time_evaluates_expressions(self):
        self.solid('source')
        self.ae.run_jsx('var c=app.project.activeItem;c.layer("source").opacity.setValue(13);c.layer("source").opacity.expression="20+time*10";c.time=1;"ok"')
        expected = self.read('app.project.activeItem.layer("source").opacity.valueAtTime(1,false)')
        self.assertEqual(self.ae.get_value('source','opacity',at_time=1), expected)
        self.assertEqual(self.ae.get_value('source','opacity'), expected)

    def test_freeze_replaces_interior_time_remap_keys(self):
        self.ae.run_jsx('var c=app.project.activeItem;var s=app.project.items.addComp("footage",32,32,1,3,30);var l=c.layers.add(s);l.name="footage";l.timeRemapEnabled=true;l.timeRemap.setValueAtTime(1,.2);l.timeRemap.setValueAtTime(2,1.7);"ok"')
        self.ae.freeze_frame('footage', .8)
        samples = self.read('(function(){var p=app.project.activeItem.layer("footage").timeRemap;var r=[];for(var i=0;i<6;i++)r.push(p.valueAtTime(i/2,false));return r;})()')
        for value in samples:
            self.assertAlmostEqual(value, .8, places=6)

    def test_unicode_line_separator_text_roundtrip(self):
        text = 'A\u2028B\u2029C'
        self.ae.add_text_layer(text, 'unicode')
        actual = self.read('app.project.activeItem.layer("unicode").property("ADBE Text Properties").property("ADBE Text Document").value.text')
        self.assertEqual(actual, text)

    def test_invalid_mask_geometry_leaves_no_orphan_mask(self):
        self.solid('source')
        before = self.read('app.project.activeItem.layer("source").property("ADBE Mask Parade").numProperties')
        try:
            self.ae.add_mask('source', [[0,0],[30,0],[0,30]], in_tangents=[[0,0]])
        except (ValueError, RuntimeError):
            pass
        self.assertEqual(self.read('app.project.activeItem.layer("source").property("ADBE Mask Parade").numProperties'), before)

    def test_null_parent_batch_rejects_missing_child_before_creation(self):
        self.solid('source')
        before = self.read('({layers:app.project.activeItem.numLayers,items:app.project.numItems,parent:app.project.activeItem.layer("source").parent})')
        try:
            self.ae.create_null_control('controller', parent_to=['source','missing'])
        except (ValueError, RuntimeError):
            pass
        after = self.read('({layers:app.project.activeItem.numLayers,items:app.project.numItems,parent:app.project.activeItem.layer("source").parent?app.project.activeItem.layer("source").parent.id:null})')
        self.assertEqual(after, before)

    def test_mask_animation_preserves_open_path_and_tangents(self):
        self.solid('source')
        incoming = [[-2,0],[0,-3],[2,0]]
        outgoing = [[2,0],[0,3],[-2,0]]
        self.ae.add_mask('source', [[0,0],[30,0],[0,30]], in_tangents=incoming, out_tangents=outgoing, closed=False)
        self.ae.animate_mask_path('source', 1, [(1,[[1,1],[31,1],[1,31]])])
        result = self.read('(function(){var s=app.project.activeItem.layer("source").property("ADBE Mask Parade").property(1).property("ADBE Mask Shape").keyValue(1);return {closed:s.closed,incoming:s.inTangents,outgoing:s.outTangents};})()')
        self.assertFalse(result['closed'])
        self.assertEqual(result['incoming'], incoming)
        self.assertEqual(result['outgoing'], outgoing)

    def test_clear_render_queue_reports_removed_count(self):
        self.ae.add_to_render_queue(); self.ae.add_to_render_queue()
        self.assertEqual(self.ae.clear_render_queue(), 'cleared:2')
        self.assertEqual(self.ae.render_queue_info(), [])


    def test_native_2d_position_accepts_numeric_property_path(self):
        self.solid('source')
        info = self.read('(function(){var l=app.project.activeItem.layer("source"),g=l.property("ADBE Transform Group"),p=g.property("ADBE Position");return {id:l.id,path:[g.propertyIndex-1,p.propertyIndex-1]};})()')
        frames = [{'time':0,'value':[23,41]},{'time':1,'value':[79,83]}]
        for dry_run in (True, False):
            result = self.ae.set_native_keyframes(info['id'], info['path'], frames, dry_run=dry_run)
            self.assertTrue(result['ok'], result)
            self.assertEqual(self.read('app.project.activeItem.layer("source").position.numKeys'), 0 if dry_run else 2)
        for t, wanted in [(0,[23,41,0]), (1,[79,83,0])]:
            self.assertEqual(self.read('app.project.activeItem.layer("source").position.valueAtTime(%d,true)' % t), wanted)
        self.ae.run_jsx('app.executeCommand(16);"undo"')
        self.assertEqual(self.read('app.project.activeItem.layer("source").position.numKeys'), 0)

    def test_native_ease_rejects_hold_only_property_before_mutation(self):
        self.solid('source')
        info = self.read('(function(){var l=app.project.activeItem.layer("source"),e=l.property("ADBE Effect Parade").addProperty("ADBE Checkbox Control"),p=e.property(1);p.setValueAtTime(0,0);p.setValueAtTime(1,1);return {id:l.id,bezier:p.isInterpolationTypeValid(KeyframeInterpolationType.BEZIER)};})()')
        self.assertFalse(info['bezier'])
        path = ['ADBE Effect Parade', 0, 1]
        before = self.ae.get_native_keyframes(info['id'], path)
        for dry_run in (True, False):
            result = self.ae.set_native_keyframe_ease(info['id'], path, [{'index':0,'temporal_ease':[[0,.3,0,.3]]}], dry_run=dry_run)
            self.assertFalse(result['ok'], result)
            self.assertIn('bezier_interpolation_not_supported', result['error'])
            self.assertEqual(result['outcome'], 'not_started')
            self.assertTrue(result['retrySafe'])
            self.assertEqual(self.ae.get_native_keyframes(info['id'], path), before)

    def test_reverse_remap_uses_visible_frames_without_old_keys(self):
        self.ae.run_jsx('var c=app.project.activeItem;var s=app.project.items.addComp("footage",32,32,1,3,30);var l=c.layers.add(s);l.name="footage";l.timeRemapEnabled=true;l.timeRemap.setValueAtTime(1,.2);l.timeRemap.setValueAtTime(2,1.7);"ok"')
        self.ae.reverse_layer('footage')
        values = self.read('(function(){var p=app.project.activeItem.layer("footage").timeRemap;return [p.valueAtTime(0,false),p.valueAtTime(1,false),p.valueAtTime(89/30,false),p.numKeys];})()')
        self.assertAlmostEqual(values[0], 89/30, places=6)
        self.assertAlmostEqual(values[1], 59/30, places=6)
        self.assertAlmostEqual(values[2], 0, places=6)
        self.assertEqual(values[3], 2)


    def test_native_effect_match_name_path_does_not_block_host(self):
        self.solid('source')
        layer = self.read('(function(){var l=app.project.activeItem.layer("source");l.property("ADBE Effect Parade").addProperty("ADBE Slider Control").property(1).setValue(42);return l.id;})()')
        named = ['ADBE Effect Parade','ADBE Slider Control','ADBE Slider Control-0001']
        a = self.ae.sample_native_property(layer, named, [0])
        b = self.ae.sample_native_property(layer, ['ADBE Effect Parade',0,1], [0])
        self.assertTrue(a['ok'], a)
        self.assertEqual(a, b)
        self.ae.run_jsx('app.project.activeItem.layer("source").property("ADBE Effect Parade").addProperty("ADBE Slider Control");"ok"')
        ambiguous = self.ae.sample_native_property(layer, named, [0])
        self.assertFalse(ambiguous['ok'], ambiguous)
        self.assertIn('ambiguous_match_name', ambiguous['error'])
        explicit = self.ae.sample_native_property(layer, ['ADBE Effect Parade',0,1], [0])
        self.assertEqual(explicit, b)

    def test_native_bad_paths_reject_without_host_dialog(self):
        self.solid('source')
        layer=self.read('app.project.activeItem.layer("source").id')
        for path, error in [(['ADBE Transform Group','ADBE Opacity',0],'cannot_descend_into_leaf'),
                            (['ADBE Transform Group',9999],'index_out_of_range'),
                            (['ADBE Transform Group','nonexistent'],'not_found')]:
            result=self.ae.sample_native_property(layer,path,[0])
            self.assertFalse(result['ok'],result)
            self.assertIn(error,result['error'])
        self.assertTrue(str(self.ae.run_jsx('app.version')).startswith('27.'))


    def test_json_queries_work_without_optional_host_json(self):
        wrapped = _wrap_jsx_for_structured_errors('JSON.stringify({value:JSON.parse("[1,null,true]")})')
        code = '(function(){var original=$.global.JSON;try{$.global.JSON=undefined;var result=eval(' + json.dumps(wrapped) + ');return result+"|"+typeof $.global.JSON;}finally{$.global.JSON=original;}})()'
        result = self.ae.run_jsx(code)
        self.assertEqual(result, '{"value":[1,null,true]}|undefined')


if __name__ == '__main__':
    unittest.main()
