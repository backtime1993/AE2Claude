from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_exporter():
    spec = importlib.util.spec_from_file_location('review_export_mobar', ROOT / 'export_mobar.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MoBarExportReviewTests(unittest.TestCase):
    def test_import_has_no_filesystem_side_effects(self):
        with patch('builtins.open', side_effect=AssertionError('unexpected file access')), \
                patch('os.makedirs', side_effect=AssertionError('unexpected directory creation')), \
                patch.object(Path, 'mkdir', side_effect=AssertionError('unexpected directory creation')):
            module = load_exporter()
        self.assertTrue(callable(module.export_scriptlets))

    def settings(self, base, items):
        path = base / 'settings.json'
        path.write_text(json.dumps({'userPanels': [{'items': items}]}), encoding='utf-8')
        return path

    def test_colliding_and_windows_reserved_names_do_not_overwrite(self):
        module = load_exporter()
        names = ['hair/front', 'hair\\front', 'HAIR-FRONT', 'CON', 'nul.jsx', ' / ', 'a:b?']
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            items = [{'type': 'scriptlet', 'name': name, 'command': f'var n={index};'}
                     for index, name in enumerate(names)]
            registry = module.export_scriptlets(self.settings(base, items), base / 'export')
            self.assertEqual(len(registry), len(names))
            self.assertEqual(len({r['file'].casefold() for r in registry}), len(names))
            self.assertEqual([r['slug'] for r in registry[:3]], ['hair-front', 'hair-front-2', 'HAIR-FRONT-3'])
            for index, row in enumerate(registry):
                self.assertEqual((base / 'export' / row['file']).read_text(), f'var n={index};')
                self.assertNotRegex(row['file'], r'[<>:"/\\|?*]')
            self.assertEqual(registry[3]['slug'], '_CON')
            self.assertEqual(registry[4]['slug'], '_nul.jsx')

    def test_existing_library_and_metadata_remain_unchanged(self):
        module = load_exporter()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            output = base / 'scripts'
            output.mkdir()
            metadata = b'[{"slug":"existing","destructive":false,"hash":"preserve"}]'
            (output / 'registry.json').write_bytes(metadata)
            settings = self.settings(base, [{'type': 'scriptlet', 'name': 'new', 'command': '1;'}])
            with self.assertRaises(FileExistsError):
                module.export_scriptlets(settings, output)
            self.assertEqual((output / 'registry.json').read_bytes(), metadata)
            self.assertEqual([p.name for p in output.iterdir()], ['registry.json'])

    def test_all_entries_validate_before_output_is_created(self):
        module = load_exporter()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            items = [{'type': 'scriptlet', 'name': 'valid', 'command': '1;'},
                     {'type': 'scriptlet', 'name': 'invalid', 'command': {'unexpected': 'object'}}]
            with self.assertRaises(ValueError):
                module.export_scriptlets(self.settings(base, items), base / 'export')
            self.assertFalse((base / 'export').exists())

    def test_default_cli_creates_separate_export_and_decodes_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings = self.settings(base, [{'type': 'scriptlet', 'name': 'Decoded',
                                             'command': json.dumps('var line="x";\n2;')}])
            result = subprocess.run([sys.executable, str(ROOT / 'export_mobar.py'), '--settings', str(settings)],
                                    cwd=base, capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            output = Path(report['output'])
            self.assertTrue(output.parent.samefile(base))
            self.assertTrue(output.name.startswith('mobar-export-'))
            self.assertEqual((output / 'Decoded.jsx').read_text(), 'var line="x";\n2;')
            self.assertFalse((base / 'scripts').exists())


if __name__ == '__main__':
    unittest.main()
