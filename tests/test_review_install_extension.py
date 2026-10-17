from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class PinCommandReviewTests(unittest.TestCase):
    def load_command(self):
        spec = importlib.util.spec_from_file_location('review_pin_cmd', ROOT / 'pin_cmd.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_pin_command_imports_repository_helper(self):
        command = self.load_command()
        self.assertEqual(Path(sys.modules[command.PinPlacer.__module__].__file__).resolve(),
                         ROOT / 'extensions/pin-clicker/python/pin_placer.py')

    def test_layer_name_is_exact_js_string_literal(self):
        command = self.load_command()
        name = 'hair\\front "left"\n\u2028'
        captured = []
        class Placer:
            def jsx(self, script):
                captured.append(script)
                return {'comp_id': 4, 'layer_index': 2}
        self.assertEqual(command._resolve_layer(Placer(), name), (4, 2))
        literal = captured[0].split('var n=', 1)[1].split('; var found=', 1)[0]
        self.assertEqual(json.loads(literal), name)
        self.assertNotIn('\n', literal)
        self.assertNotIn('\u2028', literal)

    def test_pin_command_help_works_without_legacy_checkout(self):
        result = subprocess.run([sys.executable, str(ROOT / 'pin_cmd.py'), '--help'],
                                capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ae2claude pin', result.stdout)

    def test_help_uses_utf8_even_with_western_redirected_stdio(self):
        env = {**os.environ, 'PYTHONIOENCODING': 'cp1252', 'PYTHONUTF8': '0'}
        result = subprocess.run([sys.executable, str(ROOT / 'pin_cmd.py'), '--help'],
                                env=env, capture_output=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('一行命令', result.stdout)
        self.assertIn('一键自适应打点', result.stdout)

    def test_installed_data_location_is_used_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shutil.copyfile(ROOT / 'pin_cmd.py', base / 'pin_cmd.py')
            helper = base / 'data/share/ae2claude/pin-clicker/python/pin_placer.py'
            helper.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'extensions/pin-clicker/python/pin_placer.py', helper)
            code = ('import sys,sysconfig;sys.path.insert(0,sys.argv[1]);'
                    'sysconfig.get_path=lambda name:sys.argv[2];'
                    'import pin_cmd;print(pin_cmd.PinPlacer.__name__)')
            result = subprocess.run([sys.executable, '-I', '-c', code, str(base), str(base / 'data')],
                                    capture_output=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'PinPlacer')


@unittest.skipUnless(shutil.which('node'), 'requires Node.js')
class PinClickerHandlerReviewTests(unittest.TestCase):
    def test_cep_handlers_and_generated_jsx(self):
        result = subprocess.run(['node', str(ROOT / 'tests/pinclicker_review_test.js'), str(ROOT)],
                                capture_output=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': 7, 'failed': 0})


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'requires Windows PowerShell 7')
class AutoSyncReviewTests(unittest.TestCase):
    def run_sync(self, base, fail_tests=False):
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        # All external commands and the installer are fake functions. Only the
        # original auto-sync control flow and its local checkpoint writes run.
        script = f'''
$ErrorActionPreference='Stop'
$global:reviewRoot={quote(base)}
$global:reviewFailTests=${str(fail_tests).lower()}
function git {{
    $global:LASTEXITCODE=0
    if ($args -contains '--show-current') {{ 'master' }}
    elseif ($args -contains 'rev-parse') {{ '1234567890abcdef' }}
}}
function Get-Command {{
    if ($args[0] -eq 'uv') {{ [pscustomobject]@{{Source='Invoke-ReviewUv'}} }}
    elseif ($args[0] -eq 'npm.cmd') {{ [pscustomobject]@{{Source='Invoke-ReviewNpm'}} }}
    else {{ throw ('Unexpected command: '+$args[0]) }}
}}
function Invoke-ReviewUv {{
    Add-Content -LiteralPath (Join-Path $global:reviewRoot 'calls.txt') -Value ('uv '+($args -join ' '))
    $global:LASTEXITCODE=0
    if (($args -contains 'unittest') -and $global:reviewFailTests) {{ $global:LASTEXITCODE=9 }}
}}
function Invoke-ReviewNpm {{
    Add-Content -LiteralPath (Join-Path $global:reviewRoot 'calls.txt') -Value ('npm '+($args -join ' '))
    $global:LASTEXITCODE=0
}}
function Get-Process {{ [pscustomobject]@{{Path='Invoke-ReviewInstaller'}} }}
function Invoke-ReviewInstaller {{
    Add-Content -LiteralPath (Join-Path $global:reviewRoot 'calls.txt') -Value 'INSTALL'
    $global:LASTEXITCODE=0
}}
& {quote(ROOT / 'tools/auto-sync.ps1')} -ProjectRoot {quote(base)} -SkipFetch -SkipNativeBuild
exit $LASTEXITCODE
'''
        return subprocess.run(['pwsh', '-NoProfile', '-Command', script],
                              capture_output=True, encoding='utf-8', timeout=30)

    def test_failed_validation_retries_same_head_before_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / '.git').mkdir()
            first = self.run_sync(base, fail_tests=True)
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            self.assertIn('Python tests failed', first.stdout)
            self.assertNotIn('INSTALL', (base / 'calls.txt').read_text())
            self.assertFalse((base / 'state/last-auto-validation.json').exists())

            second = self.run_sync(base)
            self.assertEqual(second.returncode, 2, second.stdout + second.stderr)
            calls = (base / 'calls.txt').read_text()
            self.assertEqual(calls.count('unittest'), 2)
            self.assertEqual(calls.count('INSTALL'), 1)
            checkpoint = json.loads((base / 'state/last-auto-validation.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(checkpoint['head'], '1234567890abcdef')
            self.assertFalse(checkpoint['nativeBuild'])

            third = self.run_sync(base)
            self.assertEqual(third.returncode, 2, third.stdout + third.stderr)
            calls = (base / 'calls.txt').read_text()
            self.assertEqual(calls.count('unittest'), 2)
            self.assertEqual(calls.count('INSTALL'), 2)


class LegacyCliReviewTests(unittest.TestCase):
    def load_cli(self):
        loader = SourceFileLoader('review_legacy_cli', str(ROOT / 'ae2claude'))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_failed_bridge_call_exits_nonzero(self):
        for result in [{'ok': False, 'error': 'missing layer'},
                       {'success': False, 'error': 'failed'}, {'outcome': 'unknown'}]:
            cli = self.load_cli()
            bridge = Mock()
            bridge.project_info.return_value = result
            with self.subTest(result=result), patch.object(cli, '_get_bridge', return_value=bridge), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    cli._invoke_method('project_info')
                self.assertNotEqual(error.exception.code, 0)

    def test_failed_jsx_and_raw_jsx_exit_nonzero(self):
        for command in ['jsx', 'return false;']:
            for result in ['{"ok":false,"error":"host failed"}', 'false']:
                cli = self.load_cli()
                bridge = Mock()
                bridge.run_jsx.return_value = result
                with self.subTest(command=command, result=result), \
                        patch.object(cli, '_get_bridge', return_value=bridge), \
                        patch.object(cli, 'req', return_value={'ok': True, 'result': result}), \
                        patch.object(sys, 'argv', ['ae2claude', command]), \
                        patch.object(sys, 'stdin', io.StringIO('return false;')), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        cli.main()
                    self.assertNotEqual(error.exception.code, 0)

    def test_comp_query_failure_never_creates_a_comp(self):
        cli = self.load_cli()
        with patch.object(cli, 'req', return_value={'ok': False, 'error': 'busy'}) as request, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli._ensure_comp()
            self.assertEqual(request.call_count, 1)

    def test_false_property_value_remains_successful(self):
        cli = self.load_cli()
        bridge = Mock()
        bridge.get_value.return_value = False
        output = io.StringIO()
        with patch.object(cli, '_get_bridge', return_value=bridge), contextlib.redirect_stdout(output):
            cli._invoke_method('get_value')
        self.assertEqual(output.getvalue().strip(), 'False')


if __name__ == '__main__':
    unittest.main()
