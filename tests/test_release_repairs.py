from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import stress_test


class BackpressureTests(unittest.TestCase):
    def request(self, responses, **kwargs):
        streams = [io.BytesIO(json.dumps(x).encode()) for x in responses]
        with patch.object(stress_test.urllib.request, 'urlopen', side_effect=streams) as send:
            with patch.object(stress_test.time, 'sleep'):
                result = stress_test.post_jsx('app.version', **kwargs)
        return result, send.call_count

    def test_only_explicit_not_started_busy_can_retry(self):
        busy = dict(ok=False, kind='busy', outcome='not_started', retrySafe=True)
        ok = dict(ok=True, result='27.0x22')
        result, calls = self.request([busy, ok], retry_busy=True)
        self.assertEqual((result, calls), (ok, 2))

    def test_unknown_write_and_validation_failure_never_replayed(self):
        for payload in [
            dict(ok=False, kind='busy', outcome='unknown', retrySafe=True),
            dict(ok=False, kind='native', outcome='not_started', retrySafe=True),
            dict(ok=False, kind='busy', outcome='not_started', retrySafe=False),
            dict(ok=False, kind='busy', outcome='not_started'),
        ]:
            with self.subTest(payload=payload):
                self.assertEqual(self.request([payload], retry_busy=True), (payload, 1))

    def test_retries_are_opt_in_and_deadline_bounded(self):
        busy = dict(ok=False, kind='busy', outcome='not_started', retrySafe=True)
        self.assertEqual(self.request([busy]), (busy, 1))
        self.assertEqual(self.request([busy], retry_busy=True, retry_seconds=0), (busy, 1))

    def test_transport_disconnect_is_not_retried(self):
        with patch.object(stress_test.urllib.request, 'urlopen', side_effect=OSError('disconnect')) as send:
            with self.assertRaises(OSError):
                stress_test.post_jsx('app.version', retry_busy=True)
        self.assertEqual(send.call_count, 1)


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh'), 'requires Windows PowerShell 7')
class InstallationTransactionTests(unittest.TestCase):
    def transaction(self, mode):
        helper = Path(__file__).resolve().parents[1] / 'tools/installation-transaction.ps1'
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        with tempfile.TemporaryDirectory(prefix='AE 安装 test ') as root:
            base = Path(root)
            source = base/'source'; dest = base/'plugins'; source.mkdir(); dest.mkdir()
            for name in ['first', 'added', 'last']:
                (source/name).write_text('new-'+name)
            for name in ['first', 'last']:
                (dest/name).write_text('old-'+name)
            prelude = ''
            if mode == 'locked':
                prelude = "$lock=[IO.File]::Open((Join-Path $dst 'last'), 'Open', 'ReadWrite', 'None')"
            if mode == 'failure':
                prelude = '''
$global:replaceCount=0
function Install-StagedFile {
    param($Stage, $Destination)
    $global:replaceCount++
    if ($global:replaceCount -eq 3) { throw 'Injected commit failure' }
    if ([IO.File]::Exists($Destination)) { [IO.File]::Replace($Stage,$Destination,[System.Management.Automation.Language.NullString]::Value) }
    else { [IO.File]::Move($Stage,$Destination) }
}
'''
            script = f'''
$ErrorActionPreference='Stop'
. {quote(helper)}
$src={quote(source)}; $dst={quote(dest)}
$entries=@('first','added','last') | ForEach-Object {{[pscustomobject]@{{source=(Join-Path $src $_);destination=(Join-Path $dst $_)}}}}
{prelude}
$errorText=$null
try {{ Invoke-DeploymentTransaction -Entries $entries -PluginDirectory $dst -BackupPath {quote(base/'backup')} }}
catch {{ $errorText=$_.Exception.Message }}
finally {{ if (Get-Variable lock -ErrorAction SilentlyContinue) {{$lock.Dispose()}} }}
@{{error=$errorText;temps=@(Get-ChildItem $dst -Filter '.ae2claude-*.tmp' -Force).Count}} | ConvertTo-Json -Compress
'''
            result = subprocess.run(['pwsh','-NoProfile','-Command',script], capture_output=True,
                                    encoding='utf-8', timeout=30, check=True)
            payload=json.loads(result.stdout)
            self.assertEqual(payload['temps'], 0, payload)
            if mode == 'success':
                self.assertIsNone(payload['error'])
                for name in ['first','added','last']:
                    self.assertEqual((dest/name).read_text(), 'new-'+name)
                self.assertEqual((base/'backup/first').read_text(), 'old-first')
                state=json.loads((base/'backup/transaction.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(state['state'],'committed')
            else:
                self.assertIsNotNone(payload['error'])
                self.assertEqual((dest/'first').read_text(),'old-first')
                self.assertEqual((dest/'last').read_text(),'old-last')
                self.assertFalse((dest/'added').exists())
                if mode == 'failure':
                    self.assertIn('Injected commit failure', payload['error'])
                    state=json.loads((base/'backup/transaction.json').read_text(encoding='utf-8-sig'))
                    self.assertEqual(state['state'],'rolled-back')

    def test_all_files_are_installed_and_verified(self):
        self.transaction('success')

    def test_locked_later_file_leaves_all_originals_unchanged(self):
        self.transaction('locked')

    def test_commit_failure_restores_originals_and_removes_only_new_files(self):
        self.transaction('failure')


class PreviewDeadlineTests(unittest.TestCase):
    def test_native_read_spends_the_same_budget_as_png_wait(self):
        from ae2claude_mcp import previews
        from unittest.mock import Mock
        bridge=Mock()
        bridge.run_jsx.return_value=json.dumps({"ok":True})
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"AE2CLAUDE_PREVIEW_ROOT":directory}):
                with patch.object(previews,'prune_previews'):
                    with patch.object(previews.time,'monotonic',side_effect=[0,2]):
                        with patch.object(previews,'_wait_for_complete_file') as wait:
                            with self.assertRaises(TimeoutError):
                                previews.render_preview(bridge,timeout_ms=100)
                        wait.assert_not_called()
        self.assertEqual(bridge.run_jsx.call_count,1)

    def test_invalid_deadline_never_dispatches(self):
        from ae2claude_mcp import previews
        from unittest.mock import Mock
        bridge=Mock()
        for value in (0, -1, True, 1.5, 120001):
            with self.assertRaises(ValueError):
                previews.render_preview(bridge,timeout_ms=value)
        bridge.run_jsx.assert_not_called()


class StressHostSelectionTests(unittest.TestCase):
    def test_wrong_host_is_rejected_before_any_pressure_or_fixture_write(self):
        for pin_version, jsx_version in [("27.0x58", "25.6.4x3"), ("25.6.4x3", "27.0x58")]:
            with self.subTest(pin=pin_version, jsx=jsx_version):
                with tempfile.TemporaryDirectory() as directory:
                    output = str(Path(directory) / "report.json")
                    def health(url):
                        if ":18889/" in url:
                            return {"status": "ok", "module_available": True}
                        package = json.loads((stress_test.ROOT / "extensions/pin-clicker/package.json").read_text(encoding="utf-8"))
                        return {"ok": True, "extension_version": package["version"], "ae": {"version": pin_version}}
                    with patch("sys.argv", ["stress_test", "--ae-major", "25", "--output", output]), \
                         patch.object(stress_test, "process_snapshot", return_value={}), \
                         patch.object(stress_test, "get_json", side_effect=health), \
                         patch.object(stress_test, "post_jsx", return_value={"ok": True, "result": jsx_version}), \
                         patch.object(stress_test, "run_parallel") as reads, \
                         patch.object(stress_test, "run_write_cycles") as writes, \
                         patch.object(stress_test, "run_agent_property_pressure") as properties:
                        with self.assertRaises(RuntimeError):
                            stress_test.main()
                        reads.assert_not_called()
                        writes.assert_not_called()
                        properties.assert_not_called()
