from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from ae2claude_mcp import script_library as library
from ae2claude_mcp import server


class ScriptLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"AE2CLAUDE_LIBRARY_DIR": str(self.root),
                                     "AE2CLAUDE_CAPTURE_SCRIPTS": "1",
                                     "AE2CLAUDE_APPROVAL_MODE": "auto",
                                     "AE2CLAUDE_KILL_SWITCH_FILE": str(self.root / "disabled")})
        env.start()
        self.addCleanup(env.stop)

    def test_dedup_promote_search_and_usage_persist(self):
        a = library.capture('app.version;')
        b = library.capture('app.version;')
        self.assertEqual(a['artifactId'], b['artifactId'])
        self.assertEqual(library.search()['total'], 0)
        library.save(a['artifactId'], '版本读取', '只读验证', ['诊断'], verified=True)
        self.assertEqual(library.search('版本')['total'], 1)
        library.capture('app.version;')
        library.record_use(a['artifactId'])
        record = library.get_script(a['artifactId'])
        self.assertEqual(record['status'], 'saved')
        self.assertTrue(record['verified'])
        self.assertEqual(record['captureCount'], 3)
        self.assertEqual(record['useCount'], 1)
        self.assertEqual(record['code'], 'app.version;')

    def test_false_uncertain_sensitive_disabled_and_io_errors_not_captured(self):
        for result in [False, '{"ok":false}', {"success": False}, {"outcome": "unknown"}]:
            self.assertEqual(library.capture_success('throw 1;', result)['status'], 'skipped')
        secret = 'var api_key = "' + 'x' * 24 + '";'
        self.assertEqual(library.capture_success(secret, 'ok')['status'], 'skipped')
        self.assertEqual(library.search(status='all')['total'], 0)
        with patch.dict(os.environ, {'AE2CLAUDE_CAPTURE_SCRIPTS': '0'}):
            self.assertEqual(library.capture_success('1;', 'ok')['status'], 'disabled')
        with patch.object(library, 'capture', side_effect=OSError('disk full')):
            result = library.capture_success('1;', 'ok')
            self.assertEqual(result['status'], 'skipped')
            self.assertNotIn('disk full', str(result))

    def test_candidate_expiry_saved_retention_and_cap(self):
        candidate = library.capture('1;')['artifactId']
        saved = library.capture('2;')['artifactId']
        library.save(saved, 'saved')
        with closing(sqlite3.connect(self.root / 'library.sqlite3')) as db, db:
            db.execute('UPDATE scripts SET updated=?', (time.time() - 8 * 86400,))
        with self.assertRaises(ValueError):
            library.get_script(candidate)
        self.assertEqual(library.get_script(saved)['status'], 'saved')
        with patch.object(library, 'MAX_CANDIDATES', 3):
            for i in range(5):
                library.capture(f'var n={i};')
        self.assertEqual(library.search(status='candidate')['total'], 3)

    def test_parallel_capture_deduplicates(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: library.capture('app.version;')['artifactId'], range(12)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(library.get_script(ids[0])['captureCount'], 12)

    def test_hash_tamper_refuses_replay(self):
        aid = library.capture('1;')['artifactId']
        with closing(sqlite3.connect(self.root / 'library.sqlite3')) as db, db:
            db.execute('UPDATE scripts SET code=? WHERE id=?', ('2;', aid))
        with self.assertRaises(ValueError):
            library.get_script(aid)

    def test_replay_is_gated_exact_and_archived_not_executed(self):
        code = 'app.version;'
        aid = library.capture(code)['artifactId']
        ae = Mock()
        ae.run_jsx.return_value = '27.0'
        with patch.object(server, 'bridge') as bridge:
            bridge.return_value.__enter__.return_value = ae
            with self.assertRaises(PermissionError):
                server.ae_replay_script(aid)
            bridge.assert_not_called()
            result = server.ae_replay_script(aid, confirm=True)
            self.assertEqual(result['artifactId'], aid)
            ae.run_jsx.assert_called_once_with(code, timeout=60_000)
            library.archive(aid)
            with self.assertRaises(ValueError):
                server.ae_replay_script(aid, confirm=True)
        self.assertEqual(library.get_script(aid)['useCount'], 1)

    def test_no_auto_retry_or_capture_when_execution_raises(self):
        ae = Mock()
        ae.run_jsx.side_effect = TimeoutError('uncertain')
        with patch.object(server, 'bridge') as bridge:
            bridge.return_value.__enter__.return_value = ae
            with self.assertRaises(TimeoutError):
                server.ae_exec('1;', confirm=True)
        self.assertEqual(ae.run_jsx.call_count, 1)
        self.assertEqual(library.search(status='all')['total'], 0)

    def test_explicit_error_result_is_not_replay_success(self):
        aid = library.capture('1;')['artifactId']
        ae = Mock()
        ae.run_jsx.return_value = '{"ok": false}'
        with patch.object(server, 'bridge') as bridge:
            bridge.return_value.__enter__.return_value = ae
            result = server.ae_replay_script(aid, confirm=True)
        self.assertEqual(result['capture']['reason'], 'script_reported_failure')
        self.assertEqual(library.get_script(aid)['useCount'], 0)

    def test_candidate_discovery_does_not_execute(self):
        library.capture('1;')
        with patch.object(server, 'bridge') as bridge:
            result = server.ae_script_library(status='candidate')
        bridge.assert_not_called()
        self.assertEqual(result['total'], 1)

    def test_readonly_blocks_promotion(self):
        aid = library.capture('1;')['artifactId']
        with patch.dict(os.environ, {'AE2CLAUDE_APPROVAL_MODE': 'readonly'}):
            with self.assertRaises(PermissionError):
                server.ae_script_library(action='save', artifact_id=aid, name='probe', confirm=True)
