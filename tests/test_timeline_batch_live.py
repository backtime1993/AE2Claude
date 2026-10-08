"""Long timelines and batch dependency safety, in an isolated empty AE project."""
import json
import os
import unittest

from ae_bridge import AEBridge
from ae2claude_mcp.agent_runtime import execute_batch


@unittest.skipUnless(os.environ.get('AE2CLAUDE_LIVE_TEST') == '1', 'requires an isolated running AE')
class TimelineBatchLiveTests(unittest.TestCase):
    def setUp(self):
        self.ae = AEBridge()
        self.addCleanup(self.ae.close)
        state = self.read('({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null,dirty:app.project.dirty,version:app.version})')
        if state['items'] or state['file'] or state['dirty']:
            self.skipTest('requires an empty, unsaved, clean acceptance project')
        self.assertTrue(state['version'].startswith(os.environ.get('AE2CLAUDE_EXPECTED_AE_MAJOR', '27') + '.'))
        self.addCleanup(self.ae.run_jsx, 'app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();"clean"')
        self.ae.create_comp('timeline batch regression', 320, 180, 30, 6000)
        self.ae.add_solid('target', [.4, .3, .2], 80, 60)
        self.layer = self.read('app.project.activeItem.layer("target").id')
        self.opacity = ['ADBE Transform Group', 'ADBE Opacity']
        self.rotation = ['ADBE Transform Group', 'ADBE Rotate Z']

    def read(self, expr):
        return json.loads(self.ae.run_jsx('JSON.stringify(' + expr + ')'))

    def long_keys(self):
        self.ae.set_keyframes('target', 'opacity', [(0, 0), (3600, 100)])

    def test_native_long_timeline_read(self):
        self.long_keys()
        result = self.ae.property_batch(self.layer, [{'action': 'get', 'path': self.opacity, 'time': 3600}], backend='native')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['value'], 100)

    def test_native_long_timeline_write_retains_frame_precision(self):
        times = [2147.5, 3600 + 1 / 30, 5999 + 1 / 30]
        result = self.ae.property_batch(self.layer, [
            {'action': 'set', 'path': self.rotation, 'time': t, 'value': i * 10}
            for i, t in enumerate(times)], backend='native')
        self.assertTrue(result['ok'], result)
        keys = self.ae.get_keyframes('target', 'rotation')
        self.assertEqual(len(keys), 3)
        for i, (time, value) in enumerate(keys):
            self.assertAlmostEqual(time, times[i], delta=.00003)
            self.assertEqual(value, i * 10)

    def test_legacy_long_timeline_reads(self):
        self.long_keys()
        for method in ['get_stream_value', 'get_stream_value_at_path']:
            with self.subTest(method=method):
                value = self.ae._run_py('layer=list(app.project.activeItem.layers)[0]\n_result=psc.' + method + '(layer,' + repr(self.opacity) + ',3600)')
                self.assertEqual(float(value), 100)

    def test_legacy_long_timeline_insert(self):
        self.ae._run_py('layer=list(app.project.activeItem.layers)[0]\n_result=psc.insert_keyframe(layer,' + repr(self.rotation) + ',4000)')
        keys = self.ae.get_keyframes('target', 'rotation')
        self.assertEqual(len(keys), 1)
        self.assertAlmostEqual(keys[0][0], 4000, delta=.00003)

    def test_shared_legacy_reader_keeps_vectors_colors_and_errors(self):
        self.ae.add_effect_by_match_name('target', 'ADBE Fill')
        self.ae.add_effect_by_match_name('target', 'ADBE Point Control')
        self.ae.run_jsx('app.project.activeItem.layer("target").property("ADBE Effect Parade").property("ADBE Point Control").property(1).setValue([12,34]);"point"')
        cases = [(self.opacity, 100),
                 # AEGP exposes Position as 3D even for a 2D AV layer.
                 (['ADBE Transform Group', 'ADBE Position'], [160, 90, 0]),
                 (['ADBE Effect Parade', 'ADBE Point Control', 'ADBE Point Control-0001'], [12, 34]),
                 (['ADBE Effect Parade', 'ADBE Fill', 'ADBE Fill-0002'], [1, 0, 0, 1])]
        for path, expected in cases:
            for method in ['get_stream_value', 'get_stream_value_at_path']:
                with self.subTest(method=method, path=path):
                    result = self.ae._run_py('import json\nlayer=list(app.project.activeItem.layers)[0]\n_result=json.dumps(psc.' + method + '(layer,' + repr(path) + ',0))')
                    self.assertEqual(json.loads(result), expected)
        self.ae.run_jsx('app.project.activeItem.layer("target").threeDLayer=true;"3D"')
        for method in ['get_stream_value', 'get_stream_value_at_path']:
            result = self.ae._run_py('import json\nlayer=list(app.project.activeItem.layers)[0]\n_result=json.dumps(psc.' + method + '(layer,["ADBE Transform Group","ADBE Position"],0))')
            self.assertEqual(json.loads(result), [160, 90, 0])
            error = self.ae._run_py('layer=list(app.project.activeItem.layers)[0]\n_result=psc.' + method + '(layer,["missing property"],0)')
            self.assertIn('path_not_found', error)

    def test_native_static_write_preserves_existing_animation(self):
        self.ae.set_keyframes('target', 'rotation', [(0, 10), (1, 70)])
        operations = [{'action': 'set', 'path': self.opacity, 'value': 12},
                      {'action': 'set', 'path': self.rotation, 'value': 40}]
        for dry_run in [True, False]:
            result = self.ae.property_batch(self.layer, operations, backend='native', dry_run=dry_run)
            self.assertFalse(result['ok'], result)
            self.assertIn('animated_property_requires_time', result['results'][1]['error'])
            self.assertTrue(all(not r['executed'] for r in result['results']), result)
            self.assertEqual(self.ae.get_value('target', 'opacity'), 100)
            self.assertEqual(self.ae.get_keyframes('target', 'rotation'), [[0, 10], [1, 70]])

    def sequential_static_rejected(self, backend):
        # Use a different spelling for the same property to verify identity,
        # rather than comparing the input path strings.
        alias = self.read('(function(){var p=app.project.activeItem.layer("target").rotation;return [p.parentProperty.propertyIndex-1,p.propertyIndex-1];})()')
        operations = [{'action': 'set', 'path': self.rotation, 'value': 10, 'time': 1},
                      {'action': 'set', 'path': alias, 'value': 40}]
        for dry_run in [True, False]:
            result = self.ae.property_batch(self.layer, operations, backend=backend, dry_run=dry_run)
            self.assertFalse(result['ok'], result)
            self.assertIn('animated_property_requires_time', result['results'][1]['error'])
            self.assertTrue(all(not r['executed'] for r in result['results']), result)
            self.assertEqual(self.ae.get_keyframes('target', 'rotation'), [])
            self.assertEqual(self.ae.get_value('target', 'rotation'), 0)

    def test_native_sequential_state_preflight(self):
        self.sequential_static_rejected('native')

    def test_jsx_sequential_state_preflight(self):
        self.sequential_static_rejected('jsx')

    def test_valid_static_then_timed_writes_still_work(self):
        for backend in ['native', 'jsx']:
            with self.subTest(backend=backend):
                self.ae.run_jsx('var p=app.project.activeItem.layer("target").rotation;while(p.numKeys)p.removeKey(1);p.setValue(0);"reset"')
                result = self.ae.property_batch(self.layer, [
                    {'action': 'set', 'path': self.rotation, 'value': 5},
                    {'action': 'set', 'path': self.rotation, 'value': 10, 'time': 1},
                    {'action': 'set', 'path': self.rotation, 'value': 20, 'time': 2},
                    {'action': 'get', 'path': self.rotation, 'time': 2}], backend=backend)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['results'][3]['value'], 20)
                self.assertEqual(self.ae.get_keyframes('target', 'rotation'), [[1, 10], [2, 20]])

    def test_native_fail_fast_false_skips_invalid_write(self):
        self.ae.set_keyframes('target', 'rotation', [(0, 10), (1, 70)])
        result = self.ae.property_batch(self.layer, [
            {'action': 'set', 'path': self.rotation, 'value': 40},
            {'action': 'set', 'path': self.opacity, 'value': 37}], backend='native', fail_fast=False)
        self.assertFalse(result['ok'], result)
        self.assertFalse(result['results'][0]['executed'])
        self.assertTrue(result['results'][1]['ok'])
        self.assertEqual(self.ae.get_value('target', 'opacity'), 37)
        self.assertEqual(self.ae.get_keyframes('target', 'rotation'), [[0, 10], [1, 70]])

    def test_failed_workflow_dependency_does_not_queue_active_comp(self):
        result = execute_batch([
            {'method': 'property_batch', 'args': [self.layer, [{'action': 'get', 'path': ['missing property']}]], 'kwargs': {'backend': 'jsx'}},
            {'method': 'add_to_render_queue', 'kwargs': {'comp_name': '$0'}},
            {'method': 'set_value', 'args': ['target', 'opacity', 37]}], confirm=True, fail_fast=False)
        self.assertFalse(result['ok'], result)
        self.assertFalse(result['results'][1]['ok'], result)
        self.assertIn('failed operation', result['results'][1]['error'])
        self.assertTrue(result['results'][2]['ok'], result)
        self.assertEqual(self.read('app.project.renderQueue.numItems'), 0)
        self.assertEqual(self.ae.get_value('target', 'opacity'), 37)

    def test_native_invalid_time_cannot_leave_an_earlier_write(self):
        with self.assertRaisesRegex(RuntimeError, 'time must be finite and within'):
            self.ae.property_batch(self.layer, [
                {'action': 'set', 'path': self.opacity, 'value': 12},
                {'action': 'set', 'path': self.rotation, 'value': 40, 'time': 86401}], backend='native')
        self.assertEqual(self.ae.get_value('target', 'opacity'), 100)
        self.assertEqual(self.ae.get_keyframes('target', 'rotation'), [])
