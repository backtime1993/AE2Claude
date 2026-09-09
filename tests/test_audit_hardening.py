from __future__ import annotations

import unittest
import threading
import time
from unittest.mock import Mock, patch

from ae2claude_mcp.agent_runtime import execute_batch, JobManager
from ae2claude_mcp.runtime import SafetyError
from ae2claude_mcp import server


class BatchPreflightTests(unittest.TestCase):
    def test_invalid_arguments_fail_before_bridge_for_dry_and_live(self):
        invalid = [
            {"method": "project_info", "kwargs": {"unknown": 1}},
            {"method": "get_layer_info"},
            {"method": "get_layer_info", "args": ["one"], "kwargs": {"name": "two"}},
        ]
        for operation in invalid:
            for dry in (True, False):
                with self.subTest(operation=operation, dry=dry):
                    with patch("ae2claude_mcp.agent_runtime.bridge") as bridge:
                        with self.assertRaises(ValueError):
                            execute_batch([{"method": "project_info"}, operation], dry_run=dry)
                        bridge.assert_not_called()

    def test_self_and_forward_references_fail_before_bridge(self):
        for reference in ("$0", "$1.file", "$99.values[0]"):
            with self.subTest(reference=reference):
                with patch("ae2claude_mcp.agent_runtime.bridge") as bridge:
                    with self.assertRaises(ValueError):
                        execute_batch([{"method": "get_layer_info", "args": [reference]}], dry_run=True)
                    bridge.assert_not_called()

    def test_previous_result_reference_passes_preflight(self):
        result = execute_batch([
            {"method": "project_info"},
            {"method": "get_layer_info", "args": ["$0.file"]},
        ], dry_run=True)
        self.assertTrue(result["ok"])

    def test_kill_switch_stops_remaining_operations_even_without_fail_fast(self):
        enabled = True
        def require_enabled():
            if not enabled:
                raise SafetyError("disabled")
        def first():
            nonlocal enabled
            enabled = False
            return {}
        fake = Mock()
        fake.project_info.side_effect = first
        context = Mock()
        context.__enter__ = Mock(return_value=fake)
        context.__exit__ = Mock(return_value=False)
        with patch("ae2claude_mcp.agent_runtime.bridge", return_value=context), patch(
            "ae2claude_mcp.agent_runtime.require_enabled", side_effect=require_enabled
        ):
            result = execute_batch([{"method": "project_info"}] * 3, fail_fast=False)
        self.assertFalse(result["ok"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["stopReason"], "disabled")
        self.assertEqual(result["completedCount"], 1)
        fake.project_info.assert_called_once()


class HealthTests(unittest.TestCase):
    def test_offline_is_not_ready(self):
        with patch.object(server, "bridge", side_effect=ConnectionError("offline")):
            for tool in (server.ae_ping, server.ae_status):
                result = tool()
                self.assertFalse(result["ok"])
                self.assertTrue(result["serviceReady"])
                self.assertFalse(result["bridgeReady"])
                self.assertFalse(result["projectReadable"])
                self.assertEqual(result["state"], "offline")

    def test_project_failure_does_not_erase_live_connection(self):
        context = Mock()
        ae = Mock()
        ae.get_connection_info.return_value = {"connected": True, "aeVersion": "27.0", "projectReadable": False, "error": "project unavailable"}
        context.__enter__ = Mock(return_value=ae)
        context.__exit__ = Mock(return_value=False)
        with patch.object(server, "bridge", return_value=context):
            result = server.ae_ping()
        self.assertFalse(result["ok"])
        self.assertTrue(result["bridgeReady"])
        self.assertFalse(result["projectReadable"])
        self.assertEqual(result["state"], "project-unavailable")

    def test_ready_and_disabled_states(self):
        live = {"connected": True, "projectReadable": True, "aeVersion": "27.0", "project": {}}
        for enabled in (True, False):
            with patch.object(server, "_connection_status", return_value=live), patch.object(server, "is_enabled", return_value=enabled):
                result = server.ae_ping()
            self.assertEqual(result["ok"], enabled)
            self.assertEqual(result["state"], "ready" if enabled else "disabled")


class ScriptTimeoutTests(unittest.TestCase):
    def test_long_sync_scripts_rejected_before_dispatch_or_checkpoint(self):
        for tool, kwargs in (
            (server.ae_exec, {"code": "noop", "checkpoint_label": "test", "confirm": True}),
            (server.ae_run_script, {"script": "diagnose-bridge"}),
        ):
            with self.subTest(tool=tool.__name__):
                with patch.object(server, "bridge") as bridge:
                    with self.assertRaisesRegex(ValueError, "ae_submit"):
                        tool(timeout_ms=600_000, **kwargs)
                    bridge.assert_not_called()

    def test_long_script_background_job_returns_before_completion(self):
        manager = JobManager()
        started = threading.Event()
        gate = threading.Event()
        context = Mock()
        ae = Mock()
        def run_script(code, timeout):
            self.assertEqual(timeout, 600_000)
            started.set()
            if not gate.wait(2):
                raise TimeoutError("test gate")
            return "done"
        ae.run_jsx.side_effect = run_script
        context.__enter__ = Mock(return_value=ae)
        context.__exit__ = Mock(return_value=False)
        try:
            with patch("ae2claude_mcp.agent_runtime.bridge", return_value=context):
                task = manager.submit([{"method": "run_jsx", "kwargs": {"code": "noop", "timeout": 600_000}}], confirm=True)
                self.assertTrue(started.wait(1))
                self.assertEqual(task["status"], "working")
                gate.set()
                deadline = time.monotonic() + 2
                while manager.get(task["taskId"])["status"] == "working" and time.monotonic() < deadline:
                    time.sleep(0.01)
                task = manager.get(task["taskId"])
                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["result"]["results"][0]["result"], "done")
        finally:
            gate.set()
            manager._executor.shutdown(wait=True)

    def test_normal_script_timeout_is_preserved(self):
        context = Mock()
        ae = Mock()
        ae.run_jsx.return_value = "ok"
        context.__enter__ = Mock(return_value=ae)
        context.__exit__ = Mock(return_value=False)
        with patch.object(server, "bridge", return_value=context):
            result = server.ae_exec("noop", timeout_ms=60_000, confirm=True)
        self.assertTrue(result["ok"])
        ae.run_jsx.assert_called_once_with("noop", timeout=60_000)


if __name__ == "__main__":
    unittest.main()
