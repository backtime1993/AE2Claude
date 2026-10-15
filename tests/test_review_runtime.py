import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ae2claude_mcp import agent_runtime, catalog, checkpoints, cli, previews, server


class RuntimeFailureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {
            'AE2CLAUDE_KILL_SWITCH_FILE': str(Path(self.temp.name) / 'disabled'),
            'AE2CLAUDE_APPROVAL_MODE': 'auto',
            'AE2CLAUDE_CAPTURE_SCRIPTS': '0',
        })
        env.start()
        self.addCleanup(env.stop)

    def test_failed_script_stops_batch_before_dependent_write(self):
        for value in ['{"ok":false,"error":"invalid layer"}',
                      '{"success":false}', '{"outcome":"unknown"}', 'false']:
            with self.subTest(value=value):
                ae = Mock()
                ae.run_jsx.return_value = value
                with patch.object(agent_runtime, 'bridge') as connection:
                    connection.return_value.__enter__.return_value = ae
                    result = agent_runtime.execute_batch([
                        {'method': 'run_jsx', 'args': ['probe();']},
                        {'method': 'create_comp', 'kwargs': {'name': 'must not run',
                         'width': 1920, 'height': 1080, 'duration': 1, 'fps': 30}},
                    ], confirm=True)
                self.assertFalse(result['ok'])
                self.assertEqual(result['completedCount'], 1)
                self.assertEqual(result['results'][0]['result'], value)
                ae.create_comp.assert_not_called()

    def test_failed_json_script_is_not_a_valid_dependency(self):
        ae = Mock()
        ae.run_jsx.return_value = '{"ok":false}'
        with patch.object(agent_runtime, 'bridge') as connection:
            connection.return_value.__enter__.return_value = ae
            result = agent_runtime.execute_batch([
                {'method': 'run_jsx', 'args': ['probe();']},
                {'method': 'get_layer_info', 'args': ['$0']},
                {'method': 'project_info'},
            ], fail_fast=False, confirm=True)
        self.assertEqual([x['ok'] for x in result['results']], [False, False, True])
        ae.get_layer_info.assert_not_called()
        ae.project_info.assert_called_once()

    def test_mcp_facades_propagate_script_failure(self):
        ae = Mock()
        ae.run_jsx.return_value = '{"ok":false,"error":"failed preflight"}'
        with patch.object(server, 'bridge') as connection:
            connection.return_value.__enter__.return_value = ae
            for result in [server.ae_exec('probe();', confirm=True),
                           server.ae_run_script('diagnose-bridge')]:
                self.assertFalse(result['ok'])
                self.assertEqual(result['error'], 'failed preflight')
        with patch.object(server, 'call_bridge_method', return_value=ae.run_jsx.return_value):
            self.assertFalse(server.ae_call('run_jsx', ['probe();'], confirm=True)['ok'])

    def test_cli_failure_has_nonzero_exit(self):
        failure = {'ok': False, 'error': 'preflight failed'}
        with patch('sys.argv', ['ae2claude', 'call', 'project_info']), \
             patch.object(cli, 'call_bridge_method', return_value=failure), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 4)
        self.assertFalse(json.loads(output.getvalue())['ok'])

    def test_cli_jsx_failure_is_reported(self):
        ae = Mock()
        ae.run_jsx.return_value = '{"success":false,"error":"failed"}'
        with patch.object(cli, 'bridge') as connection:
            connection.return_value.__enter__.return_value = ae
            args = cli.build_parser().parse_args(['jsx', 'probe();', '--confirm'])
            self.assertFalse(cli.dispatch(args)['ok'])

    def test_false_property_and_json_text_remain_valid_values(self):
        for value in [False, '{"ok":false}', None, 0]:
            with self.subTest(value=value), \
                 patch.object(server, 'call_bridge_method', return_value=value):
                self.assertTrue(server.ae_call('get_property')['ok'])


class CheckpointRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'project.aep'
        self.source.write_bytes(b'current edits')
        self.store = checkpoints.CheckpointStore(self.root / 'snapshots', keep=1)

    def snapshot(self, identifier, timestamp='2000-01-01T00:00:00'):
        self.store.aep_path(str(self.source), identifier).write_bytes(b'old checkpoint')
        self.store.write_meta(str(self.source), identifier, {'timestamp': timestamp})

    def test_revert_stages_target_before_recovery_prunes_it(self):
        self.snapshot('original')
        source, store = self.source, self.store

        class FakeAE:
            def __init__(self):
                self.closed = False

            def project_info(self):
                return {'file': str(source)}

            def run_jsx(self, code, timeout):
                destination = re.search(r'var destination = new File\((".*?")\);', code)
                if destination:
                    Path(json.loads(destination.group(1))).write_bytes(source.read_bytes())
                    return json.dumps({'ok': True, 'sourceProjectPath': str(source)})
                if 'app.project.close' in code:
                    self.closed = True
                    return '{"ok":true}'
                if 'app.open' in code:
                    self.closed = False
                    return json.dumps({'ok': True, 'path': str(source)})
                raise AssertionError('Unexpected JSX')

        ae = FakeAE()
        result = checkpoints.revert_checkpoint(ae, 'original', store=store)
        self.assertTrue(result['ok'])
        self.assertEqual(source.read_bytes(), b'old checkpoint')
        self.assertFalse(ae.closed)
        self.assertEqual(store.lookup(str(source), result['recoveryCheckpoint']).read_bytes(),
                         b'current edits')
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_bad_target_copy_does_not_close_project(self):
        self.snapshot('original')
        ae = Mock()
        ae.project_info.return_value = {'file': str(self.source)}
        with patch.object(checkpoints.shutil, 'copy2', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                checkpoints.revert_checkpoint(ae, 'original', store=self.store)
        ae.run_jsx.assert_not_called()

    def test_prune_is_not_limited_by_display_page(self):
        for index in range(205):
            self.snapshot(f'checkpoint_{index}', f'{index:06d}')
        removed = self.store.prune(str(self.source))
        self.assertEqual(len(removed), 204)
        self.assertEqual(len(list(self.store.project_dir(str(self.source)).glob('*.aep'))), 1)

    def test_corrupt_metadata_cannot_redirect_pruning(self):
        outside = self.root / 'important.aep'
        outside.write_bytes(b'preserve')
        directory = self.store.project_dir(str(self.source))
        for index, data in enumerate([[], {'id': '../../important', 'timestamp': '0000'},
                                      {'id': None}, {'id': 'missing', 'sourceProjectPath': 3}]):
            (directory / f'bad{index}.json').write_text(json.dumps(data), encoding='utf-8')
        self.snapshot('current')
        self.assertEqual([item['id'] for item in self.store.list(str(self.source))], ['current'])
        self.store.prune(str(self.source))
        self.assertEqual(outside.read_bytes(), b'preserve')


class PreviewOwnershipTests(unittest.TestCase):
    def test_cleanup_preserves_unrelated_png_in_configured_directory(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'AE2CLAUDE_PREVIEW_ROOT': directory}):
            root = Path(directory)
            for name in ['user-reference.png', 'frame-old.png', 'grid-old.png',
                         'diff-old.png', 'compare-old.png', 'capture-old.json',
                         'model-old.webp']:
                path = root / name
                path.write_bytes(b'keep unrelated files')
                os.utime(path, (1, 1))
            self.assertEqual(previews.prune_previews(), 6)
            self.assertEqual((root / 'user-reference.png').read_bytes(), b'keep unrelated files')


class CatalogDefaultsTests(unittest.TestCase):
    def test_registry_entries_without_modes_can_run_with_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'probe.jsx').write_text('42;', encoding='utf-8')
            (root / 'registry.json').write_text(json.dumps([
                {'slug': 'probe', 'name': 'Probe', 'file': 'probe.jsx'}
            ]), encoding='utf-8')
            entry = catalog.resolve_script('probe', root)
            self.assertEqual(entry['modes'], ['default', 'ctrl', 'alt'])
            self.assertEqual(catalog.prepare_script(entry, script_root=root), '42;')

    def test_every_bundled_script_supports_its_default_mode(self):
        for entry in catalog.load_script_registry():
            with self.subTest(script=entry['slug']):
                self.assertTrue(catalog.prepare_script(entry))


if __name__ == '__main__':
    unittest.main()
