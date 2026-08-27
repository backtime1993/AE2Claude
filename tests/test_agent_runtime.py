from __future__ import annotations

import json
import threading
import time
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from ae_bridge import AEBridge
from ae2claude_mcp.agent_runtime import (
    EventLog,
    JobManager,
    execute_batch,
    resolve_references,
)
from ae2claude_mcp.capabilities import capabilities, method_descriptor
from ae2claude_mcp.cli import build_parser
from ae2claude_mcp.properties import normalize_layer_ref, normalize_path, property_batch


class PropertyGraphTests(unittest.TestCase):
    def test_stable_layer_and_mixed_path_normalization(self) -> None:
        self.assertEqual(normalize_layer_ref(42), {"id": 42})
        self.assertEqual(normalize_layer_ref({"index": 2}), {"index": 2})
        self.assertEqual(
            normalize_path(["ADBE Effect Parade", 0, "ADBE Gaussian Blur 2-0001"]),
            ["ADBE Effect Parade", 0, "ADBE Gaussian Blur 2-0001"],
        )
        with self.assertRaises(ValueError):
            normalize_layer_ref({"id": 1, "name": "ambiguous"})
        with self.assertRaises(ValueError):
            normalize_path([True])

    def test_property_batch_falls_back_as_one_jsx_dispatch(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.timeout = 30
        ae._run_py = Mock(side_effect=RuntimeError("no attribute agent_stream_batch"))
        ae.run_jsx = Mock(
            return_value=json.dumps(
                {
                    "ok": True,
                    "backend": "jsx-single-dispatch",
                    "results": [{"index": 0, "ok": True, "value": [10, 20]}],
                }
            )
        )
        result = property_batch(
            ae,
            {"id": 7},
            [{"action": "get", "path": ["ADBE Transform Group", "ADBE Position"]}],
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["fallbackReason"], "native_agent_api_unavailable")
        self.assertEqual(ae._run_py.call_count, 1)
        self.assertEqual(ae.run_jsx.call_count, 1)
        self.assertIn("jsx-single-dispatch", ae.run_jsx.return_value)


class CapabilityTests(unittest.TestCase):
    def test_property_batch_is_self_describing(self) -> None:
        descriptor = method_descriptor("property_batch")
        self.assertEqual(descriptor["risk"], "write")
        self.assertEqual(descriptor["category"], "property")
        self.assertIn("operations", descriptor["inputSchema"]["required"])
        result = capabilities(query="property_batch")
        self.assertEqual(result["protocol"], "ae2claude.agent/v1")
        self.assertTrue(result["features"]["singleDispatchPropertyBatch"])
        self.assertEqual(result["methodCount"], 1)


class BatchRuntimeTests(unittest.TestCase):
    def test_undo_name_is_json_escaped(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.run_jsx = Mock()
        ae.begin_undo('agent" );app.project.close();//')
        code = ae.run_jsx.call_args.args[0]
        self.assertEqual(
            code,
            'app.beginUndoGroup("agent\\\" );app.project.close();//");',
        )

    def test_nested_result_references(self) -> None:
        prior = [{"layer": {"id": 9}, "values": [12, 24]}]
        self.assertEqual(resolve_references("$0.layer.id", prior), 9)
        self.assertEqual(resolve_references({"x": "$0.values[1]"}, prior), {"x": 24})

    def test_batch_uses_one_bridge_and_result_chaining(self) -> None:
        class FakeBridge:
            def __init__(self) -> None:
                self.undo = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def begin_undo(self, name: str) -> None:
                self.undo.append(("begin", name))

            def end_undo(self) -> None:
                self.undo.append(("end", None))

            def project_info(self):
                return {"file": "Layer A"}

            def get_layer_info(self, name: str):
                return {"name": name}

        fake = FakeBridge()
        with patch("ae2claude_mcp.agent_runtime.bridge", return_value=fake):
            result = execute_batch(
                [
                    {"method": "project_info"},
                    {"method": "get_layer_info", "args": ["$0.file"]},
                ]
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"][1]["result"], {"name": "Layer A"})
        self.assertEqual(fake.undo, [])

    def test_event_cursor_and_wait_contract(self) -> None:
        events = EventLog(capacity=3)
        first = events.emit("one")
        events.emit("two")
        result = events.read(after=first["sequence"])
        self.assertEqual([event["type"] for event in result["events"]], ["two"])
        self.assertGreaterEqual(result["cursor"], 2)

    def test_background_job_reaches_terminal_state(self) -> None:
        manager = JobManager(max_pending=2, ttl_ms=60_000)
        completed = {"ok": True, "requestId": "ignored", "results": []}
        with patch("ae2claude_mcp.agent_runtime.execute_batch", return_value=completed):
            task = manager.submit([{"method": "project_info"}])
            deadline = time.time() + 2
            while time.time() < deadline:
                task = manager.get(task["taskId"])
                if task["status"] != "working":
                    break
                time.sleep(0.01)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], completed)

    def test_queued_job_cancellation_does_not_deadlock(self) -> None:
        manager = JobManager(max_pending=2, ttl_ms=60_000)
        gate = threading.Event()
        call_count = 0

        def execute(*_args, **options):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                gate.wait(2)
            return {"ok": True, "cancelled": False, "results": []}

        with patch("ae2claude_mcp.agent_runtime.execute_batch", side_effect=execute):
            manager.submit([{"method": "project_info"}])
            queued = manager.submit([{"method": "project_info"}])
            cancelled = manager.cancel(queued["taskId"])
            gate.set()
        self.assertEqual(cancelled["status"], "cancelled")

    def test_task_created_event_precedes_fast_completion(self) -> None:
        manager = JobManager(max_pending=1, ttl_ms=60_000)
        completed = {"ok": True, "cancelled": False, "results": []}
        with (
            patch("ae2claude_mcp.agent_runtime.execute_batch", return_value=completed),
            patch("ae2claude_mcp.agent_runtime.EVENTS.emit") as emit,
        ):
            task = manager.submit([{"method": "project_info"}])
            deadline = time.time() + 2
            while task["status"] == "working" and time.time() < deadline:
                time.sleep(0.01)
                task = manager.get(task["taskId"])
        event_names = [
            call.args[0]
            for call in emit.call_args_list
            if call.kwargs.get("taskId") == task["taskId"]
        ]
        self.assertLess(event_names.index("task.created"), event_names.index("task.completed"))


class CliTests(unittest.TestCase):
    def test_structured_property_command_parsing(self) -> None:
        args = build_parser().parse_args(
            [
                "--format", "json", "get", "--layer", "id:42",
                "--path", '["ADBE Transform Group","ADBE Opacity"]',
            ]
        )
        self.assertEqual(args.layer, {"id": 42})
        self.assertEqual(args.path[-1], "ADBE Opacity")


if __name__ == "__main__":
    unittest.main()
