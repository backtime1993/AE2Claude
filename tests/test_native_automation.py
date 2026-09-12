from __future__ import annotations

import http.client
import json
import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ae2claude_server as native_server
from ae_bridge import AEBridge
from ae_native_protocol import normalize_request, quantized_time
from ae2claude_mcp import server as mcp_server
from ae2claude_mcp.runtime import SafetyError, classify_bridge_method

PATH = ["ADBE Transform Group", "ADBE Position"]
FRAME = {"time": 0, "value": [10, 20]}


class NativeValidationTests(unittest.TestCase):
    def test_defaults_are_read_only_and_comp_focus_is_optional(self):
        result = normalize_request("set_keyframes", {"layer_id": 7, "path": PATH, "keyframes": [FRAME]})
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["comp_id"], 0)
        self.assertEqual(result["keyframes"][0]["value"], [10.0, 20.0])

    def test_rejects_malformed_keys_before_dispatch(self):
        bad = [[], [FRAME] * 4097, [{"time": True, "value": 1}],
               [{"time": float("inf"), "value": 1}],
               [{"time": 0, "value": float("nan")}],
               [{"time": 0, "value": [True, 2]}],
               [{"time": 0, "value": [1]}],
               [{"time": 0, "value": 1, "delete": True}],
               [{"time": 2, "value": 1}, {"time": 1, "value": 1}],
               [{"time": 0, "value": 1}, {"time": 0.0000001, "value": 1}]]
        for frames in bad:
            with self.subTest(frames=str(frames)[:80]), self.assertRaises(ValueError):
                normalize_request("set_keyframes", {"layer_id": 1, "path": PATH, "keyframes": frames})

    def test_paths_and_ids_cannot_be_coerced_to_other_objects(self):
        for change in ({"layer_id": True}, {"layer_id": "1"}, {"comp_id": -1},
                       {"path": [True]}, {"path": [-1]}, {"path": ["a\0b"]},
                       {"path": []}, {"path": ["x"] * 65}, {"unexpected": "value"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_request("sample_property", {"layer_id": 1, "path": PATH, "times": [0], **change})

    def test_large_time_and_quantization_match_native_contract(self):
        self.assertEqual(quantized_time(-0.0000005), -0.000001)
        self.assertEqual(quantized_time(3600.033333), 3600.03333)
        frames = [{"time": 3600 + i / 29.97, "value": i} for i in range(4096)]
        self.assertEqual(len(normalize_request("set_keyframes", {"layer_id": 1, "path": PATH, "keyframes": frames})["keyframes"]), 4096)

    def test_matrix_and_sample_limits(self):
        self.assertEqual(len(normalize_request("sample_property", {"layer_id": 1, "path": PATH, "times": [0] * 2048})["times"]), 2048)
        for operation, arguments in (
            ("layer_transforms", {"layer_ids": list(range(1,65)), "times": [0]*17}),
            ("sample_property", {"layer_id": 1, "path": PATH, "times": [0]*2049}),
            ("snapshot", {"max_items": 2001}),
            ("snapshot", {"max_layers": False}),
            ("get_keyframes", {"layer_id": 1, "path": PATH, "start_index": -1}),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                normalize_request(operation, arguments)

    def test_readonly_policy_blocks_writes_but_allows_dry_run(self):
        self.assertEqual(classify_bridge_method("sample_native_property"), "read")
        self.assertEqual(classify_bridge_method("get_native_layer_transforms"), "read")
        self.assertEqual(classify_bridge_method("set_native_keyframes"), "write")
        with patch.dict(os.environ, {"AE2CLAUDE_APPROVAL_MODE": "readonly"}), patch.object(mcp_server, "require_enabled"), patch.object(mcp_server, "bridge") as bridge:
            mcp_server.ae_set_native_keyframes(1, PATH, [FRAME], dry_run=True)
            bridge.reset_mock()
            with self.assertRaises(SafetyError):
                mcp_server.ae_set_native_keyframes(1, PATH, [FRAME], dry_run=False, confirm=True)
            bridge.assert_not_called()


class NativeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.http = native_server._AEHTTPServer(("127.0.0.1", 0), native_server._AEHandler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.ae = AEBridge.__new__(AEBridge)
        self.ae._base_url = f"http://127.0.0.1:{self.http.server_port}"
        self.ae.timeout = 2
        self.ae.run_jsx = Mock(side_effect=AssertionError("JSX fallback forbidden"))
        self.ae._run_py = Mock(side_effect=AssertionError("Python evaluation forbidden"))

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        try:
            conn.request(method, path, body)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    def test_native_endpoint_uses_json_and_exactly_one_native_call(self):
        stub = Mock(return_value={"ok": True, "values": [1, 2], "dispatches": 1})
        with patch.object(native_server, "psc", SimpleNamespace(native_sample_property=stub)), patch.object(native_server, "_execute_code") as evaluate:
            result = self.ae.sample_native_property(8, PATH, [0,1], comp_id=31)
            self.assertEqual(result["values"], [1,2])
            self.assertEqual(stub.call_count, 1)
            self.assertEqual(stub.call_args.kwargs["comp_id"], 31)
            evaluate.assert_not_called()

    def test_diagnostics_refresh_on_a_reused_connection(self):
        telemetry = Mock(side_effect=[{"submitted": 4}, {"submitted": 9}])
        with patch.object(native_server, "psc", SimpleNamespace(bridgeDiagnostics=telemetry)):
            self.assertEqual(self.ae.get_native_diagnostics()["native"]["submitted"], 4)
            self.assertEqual(self.ae.get_native_diagnostics()["native"]["submitted"], 9)
        self.ae.run_jsx.assert_not_called()
        self.ae._run_py.assert_not_called()

    def test_unicode_strings_are_data_without_eval(self):
        text = '关键帧 "quoted" \\ path\n'; path = ["ADBE Effect Parade", 0, "包含引号'的属性"]
        stub = Mock(return_value={"ok": True, "outcome": "completed", "written": 1})
        with patch.object(native_server, "psc", SimpleNamespace(native_set_keyframes=stub)):
            self.assertTrue(self.ae.set_native_keyframes(1,path,[FRAME],dry_run=False,undo_name=text)["ok"])
        self.assertEqual(stub.call_args.kwargs["undo_name"], text)
        self.assertEqual(stub.call_args.kwargs["path"], path)

    def test_busy_rejects_native_and_health_does_not_wait_for_it(self):
        entered, release = threading.Event(), threading.Event()
        def slow(**kwargs):
            entered.set()
            if not release.wait(4): raise RuntimeError("test timeout")
            return {"ok": True}
        outcome = []
        with patch.object(native_server, "psc", SimpleNamespace(native_snapshot=slow)):
            worker = threading.Thread(target=lambda: outcome.append(self.ae.get_native_snapshot()))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                started=time.monotonic()
                self.assertTrue(self.request("GET","/health")[1]["execution"]["busy"])
                self.assertLess(time.monotonic()-started,1)
                for endpoint, body in (("/native",json.dumps({"operation":"snapshot","arguments":{}})), ("/jsx","6*7"), ("/exec","6*7")):
                    result=self.request("POST",endpoint,body)[1]
                    self.assertEqual((result["kind"],result["outcome"]),("busy","not_started"))
            finally:
                release.set(); worker.join(4)
        self.assertEqual(outcome,[{"ok":True}])

    def test_invalid_requests_never_reach_cpp(self):
        stub=Mock()
        with patch.object(native_server,"psc",SimpleNamespace(native_set_keyframes=stub)):
            for document in ([], {}, {"operation":"__dict__","arguments":{}},
                             {"operation":"set_keyframes","arguments":{"layer_id":1,"path":PATH,"keyframes":[{"time":0,"value":True}]}},
                             {"operation":"snapshot","arguments":{},"source":"execute me"}):
                result=self.request("POST","/native",json.dumps(document))[1]
                self.assertFalse(result["ok"])
                self.assertEqual(result["outcome"],"not_started")
            stub.assert_not_called()
        self.assertEqual(self.request("POST","/native","{broken")[0],400)

    def test_native_missing_and_unknown_failure_do_not_fallback(self):
        with patch.object(native_server,"psc",None):
            self.assertEqual(self.ae.get_native_snapshot()["kind"],"native_unavailable")
        stub=Mock(side_effect=RuntimeError("failed after committing keys"))
        with patch.object(native_server,"psc",SimpleNamespace(native_set_keyframes=stub)):
            result=self.ae.set_native_keyframes(1,PATH,[FRAME],dry_run=False)
        self.assertEqual(result["outcome"],"unknown")
        self.assertFalse(result["retrySafe"])
        self.assertEqual(stub.call_count,1)
        self.ae.run_jsx.assert_not_called(); self.ae._run_py.assert_not_called()

    def test_partial_native_result_is_preserved(self):
        failure={"ok":False,"written":0,"outcome":"unknown","retrySafe":False,"error":"commit failed"}
        with patch.object(native_server,"psc",SimpleNamespace(native_set_keyframes=lambda **kw:failure)):
            self.assertEqual(self.ae.set_native_keyframes(1,PATH,[FRAME],dry_run=False),failure)

    def test_client_rejects_invalid_input_before_network(self):
        with patch("ae_bridge._local_urlopen") as send:
            with self.assertRaises(ValueError):
                self.ae.set_native_keyframes(1,PATH,[{"time":0,"value":True}],dry_run=False)
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
