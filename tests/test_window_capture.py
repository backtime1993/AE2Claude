from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image
from ae2claude_mcp import window_capture as capture


def window(hwnd=1, pid=10, cls='AE_CApplication_27.0', owner=0, enabled=False):
    return dict(hwnd=hwnd, pid=pid, **{'class':cls}, owner=owner, enabled=enabled,
                minimized=False, hung=False, rect=[0,0,200,100], title='')


class WindowCaptureTests(unittest.TestCase):
    def test_unsupported_platform_never_starts_worker(self):
        with patch.object(capture, 'IS_WINDOWS', False), patch.object(capture, 'worker') as worker:
            self.assertEqual(capture.capture_blocked('unused')['state'], 'unsupported_platform')
            worker.assert_not_called()

    def test_gate_requires_disabled_main_and_same_process(self):
        main = window()
        modal = window(2, cls='#32770', owner=1, enabled=True)
        other = window(3, pid=11, cls='#32770', owner=1, enabled=True)
        _, dialogs, state = capture.select_dialogs([main,modal,other], lambda _:0)
        self.assertEqual(dialogs, [modal])
        self.assertEqual(state, 'blocked')
        main['enabled'] = True
        self.assertEqual(capture.select_dialogs([main,modal], lambda _:0)[1], [])
        main.update(enabled=False, minimized=True)
        self.assertEqual(capture.select_dialogs([main,modal], lambda _:0)[2], 'main_minimized')

    def test_ambiguous_instances_and_owner_cycle(self):
        main = window()
        self.assertEqual(capture.select_dialogs([main,window(8,20)], lambda _:0)[2], 'ambiguous_ae_instances')
        foreign = window(2, cls='Other', owner=3, enabled=True)
        self.assertEqual(capture.select_dialogs([main,foreign], lambda n:n)[1], [])
        owned = window(4, cls='CustomAE', owner=5, enabled=True)
        self.assertEqual(capture.select_dialogs([main,owned], lambda n:1 if n==5 else 0)[1], [owned])

    def test_missing_main_is_not_blocked(self):
        self.assertEqual(capture.select_dialogs([], lambda _:0), (None, [], 'ae_not_found'))

    def test_idle_does_not_create_directory_or_call_capture_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'must-not-exist'
            state = dict(ok=True, state='not_blocked', blocked=False, dialogs=[])
            with patch.object(capture, 'IS_WINDOWS', True), patch.object(capture, 'worker', return_value=state) as worker:
                result = capture.capture_blocked(output)
            self.assertEqual(result['captures'], [])
            self.assertFalse(output.exists())
            self.assertEqual(worker.call_count, 1)

    def test_worker_timeout_is_reported_and_lock_released(self):
        with patch.object(capture, 'IS_WINDOWS', True), patch.object(capture, 'worker', side_effect=subprocess.TimeoutExpired('probe',6)):
            self.assertEqual(capture.capture_blocked('unused')['state'], 'inspection_failed')
        self.assertTrue(capture._CAPTURE_LOCK.acquire(False))
        capture._CAPTURE_LOCK.release()

    def test_reject_concurrent_capture_without_worker(self):
        capture._CAPTURE_LOCK.acquire()
        try:
            with patch.object(capture, 'IS_WINDOWS', True), patch.object(capture, 'worker') as worker:
                self.assertEqual(capture.capture_blocked('unused')['state'], 'capture_busy')
                worker.assert_not_called()
        finally:
            capture._CAPTURE_LOCK.release()

    def test_capture_failure_and_truncation_are_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = dict(ok=True, state='blocked', blocked=True, dialogs=[window(i, cls='#32770') for i in [2,3,4]])
            with patch.object(capture, 'IS_WINDOWS', True), patch.object(capture, 'worker', side_effect=[state,subprocess.TimeoutExpired('capture',6),RuntimeError('worker failed')]) as worker:
                result = capture.capture_blocked(tmp)
            self.assertFalse(result['ok'])
            self.assertTrue(result['truncated'])
            self.assertEqual(len(result['captures']),2)
            self.assertEqual(result['captures'][0]['reason'],'capture_timeout')
            self.assertEqual(worker.call_count,3)

    def test_blank_capture_is_not_returned_as_a_valid_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            def worker(args, timeout):
                if args[0]=='enumerate':
                    return dict(ok=True, state='blocked', blocked=True, dialogs=[window(2, cls='#32770')])
                path=Path(args[-1]); path.write_bytes(b'partial')
                return dict(ok=True, suspectBlank=True, path=str(path))
            with patch.object(capture,'IS_WINDOWS',True), patch.object(capture,'worker',side_effect=worker):
                result=capture.capture_blocked(tmp)
            self.assertFalse(result['ok'])
            self.assertNotIn('path',result['captures'][0])
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_capture_revalidates_identity_and_never_captures_main(self):
        main, dialog = window(), window(2, cls='#32770',owner=1)
        with patch.object(capture,'enumerate_ui',return_value=dict(blocked=True,main=main,dialogs=[dialog])):
            self.assertFalse(capture.print_window(main,Path('unused'))['ok'])
            changed = {**dialog,'pid':999}
            self.assertFalse(capture.print_window(changed,Path('unused'))['ok'])

    def test_mcp_image_roundtrip_without_bridge_and_kill_switch(self):
        from ae2claude_mcp import server
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source=root/'ae-ui-test.png'; Image.new('RGB',(100,80),'blue').save(source)
            captured=dict(ok=True,path=str(source),hwnd=2,pid=10)
            state=dict(ok=True,blocked=True,state='blocked',captures=[captured])
            with patch.dict(os.environ,{'AE2CLAUDE_PREVIEW_ROOT':tmp}), patch.object(server,'require_enabled') as enabled, patch.object(server,'bridge') as bridge, patch.object(capture,'capture_blocked',return_value=state):
                result=server.ae_capture_blocked_ui()
                enabled.assert_called_once(); bridge.assert_not_called()
                images=[c for c in result.content if c.type=='image']
                self.assertEqual(len(images),1)
                self.assertEqual(images[0].mimeType,'image/webp')
                self.assertGreater(len(base64.b64decode(images[0].data)),0)
                self.assertEqual(result.structuredContent['modelPreviews'][0]['hwnd'],2)
            with patch.object(server,'require_enabled',side_effect=RuntimeError('disabled')), patch.object(capture,'capture_blocked') as probe:
                with self.assertRaises(RuntimeError): server.ae_capture_blocked_ui()
                probe.assert_not_called()

    def test_pruning_only_owned_expired_capture(self):
        from ae2claude_mcp.previews import prune_previews
        with tempfile.TemporaryDirectory() as tmp:
            owned=Path(tmp)/'ae-ui-expired.png'; reference=Path(tmp)/'reference.png'
            for file in [owned,reference]:
                file.write_bytes(b'test'); os.utime(file,(0,0))
            with patch.dict(os.environ,{'AE2CLAUDE_PREVIEW_ROOT':tmp}):
                self.assertEqual(prune_previews(),1)
            self.assertTrue(reference.exists())


if __name__ == '__main__':
    unittest.main()
