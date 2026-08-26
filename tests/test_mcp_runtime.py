from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ae_bridge import AEBridge, JSXExecutionError, _wrap_jsx_for_structured_errors
from ae2claude_mcp.catalog import (
    load_script_registry,
    prepare_script,
    resolve_script,
    script_path,
    search_scripts,
)
from ae2claude_mcp.checkpoints import CheckpointStore, create_checkpoint, project_key
from ae2claude_mcp.previews import _wait_for_complete_file
from ae2claude_mcp.runtime import (
    SafetyError,
    authorize,
    classify_bridge_method,
    is_enabled,
    set_enabled,
)


class RuntimeTests(unittest.TestCase):
    def test_method_risk_classification(self) -> None:
        self.assertEqual(classify_bridge_method("project_info"), "read")
        self.assertEqual(classify_bridge_method("list_layers"), "read")
        self.assertEqual(classify_bridge_method("search_effects"), "read")
        self.assertEqual(classify_bridge_method("add_text_layer"), "write")
        self.assertEqual(classify_bridge_method("remove_layer"), "destructive")
        self.assertEqual(classify_bridge_method("run_jsx"), "destructive")

    def test_auto_requires_confirmation_only_for_destructive(self) -> None:
        with patch.dict(os.environ, {"AE2CLAUDE_APPROVAL_MODE": "auto"}):
            authorize("write")
            with self.assertRaises(SafetyError):
                authorize("destructive")
            authorize("destructive", confirm=True)

    def test_readonly_blocks_writes(self) -> None:
        with patch.dict(os.environ, {"AE2CLAUDE_APPROVAL_MODE": "readonly"}):
            authorize("read")
            with self.assertRaises(SafetyError):
                authorize("write", confirm=True)

    def test_kill_switch_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = str(Path(td) / "disabled")
            with patch.dict(os.environ, {"AE2CLAUDE_KILL_SWITCH_FILE": target}):
                set_enabled(False)
                self.assertFalse(is_enabled())
                set_enabled(True)
            self.assertTrue(is_enabled())


class JSXGuardTests(unittest.TestCase):
    def test_wrapper_json_encodes_source_and_returns_structured_fields(self) -> None:
        source = 'var name="含引号";\nthrow new Error(name);'
        wrapped = _wrap_jsx_for_structured_errors(source)
        self.assertIn("return eval(" + json.dumps(source, ensure_ascii=True) + ")", wrapped)
        self.assertIn("__ae2claude_error__", wrapped)
        self.assertIn("fileName", wrapped)
        self.assertIn("line", wrapped)

    def test_jsx_execution_error_is_machine_readable(self) -> None:
        payload = {"ok": False, "kind": "jsx", "error": "probe", "line": 7}
        error = JSXExecutionError(payload)
        self.assertEqual(error.payload, payload)
        self.assertEqual(json.loads(str(error)), payload)

    def test_list_layers_guards_an_empty_project(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.run_jsx = Mock(return_value="[]")  # type: ignore[method-assign]
        self.assertEqual(ae.list_layers(), [])
        code = ae.run_jsx.call_args.args[0]
        self.assertIn("if(!c || !(c instanceof CompItem))return \"[]\"", code)


class CheckpointStoreTests(unittest.TestCase):
    def test_same_basename_different_paths_do_not_collide(self) -> None:
        self.assertNotEqual(
            project_key(r"C:\\a\\project.aep"),
            project_key(r"D:\\b\\project.aep"),
        )

    def test_metadata_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = CheckpointStore(root=Path(td), keep=2)
            project = r"C:\\work\\shot.aep"
            checkpoint_id = "1234_abcd1234"
            aep = store.aep_path(project, checkpoint_id)
            aep.write_bytes(b"fake-aep")
            store.write_meta(
                project,
                checkpoint_id,
                {"label": "before edit", "sizeBytes": aep.stat().st_size},
            )
            entries = store.list(project)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], checkpoint_id)
            self.assertEqual(entries[0]["label"], "before edit")
            json.loads(store.meta_path(project, checkpoint_id).read_text(encoding="utf-8"))

    def test_preview_file_stability_wait(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            preview = Path(td) / "frame.png"
            preview.write_bytes(b"png-data")
            self.assertEqual(_wait_for_complete_file(preview, 1.0), 8)

    def test_checkpoint_creation_with_saved_project(self) -> None:
        class FakeBridge:
            def project_info(self) -> dict[str, str]:
                return {"file": project}

            def run_jsx(self, code: str, timeout: int) -> str:
                match = re.search(r"var destination = new File\((\".*?\")\);", code)
                if match is None:
                    raise AssertionError("destination missing from JSX")
                destination = Path(json.loads(match.group(1)))
                destination.write_bytes(b"fake-aep")
                return json.dumps(
                    {
                        "ok": True,
                        "sourceProjectPath": project,
                        "savedTo": str(destination),
                        "sizeBytes": destination.stat().st_size,
                        "activeCompId": "42",
                        "currentTime": 1.25,
                    }
                )

        with tempfile.TemporaryDirectory() as td:
            project = str(Path(td) / "shot.aep")
            Path(project).write_bytes(b"original")
            store = CheckpointStore(root=Path(td) / "checkpoints", keep=2)
            result = create_checkpoint(FakeBridge(), "before edit", store=store)  # type: ignore[arg-type]
            self.assertTrue(result["ok"])
            self.assertEqual(result["label"], "before edit")
            self.assertTrue(Path(result["path"]).exists())


class EffectCatalogTests(unittest.TestCase):
    def test_describe_effect_json_encodes_match_name(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.run_jsx = Mock(return_value='{"error":"not available"}')  # type: ignore[method-assign]
        match_name = 'Pseudo/Quote"\\Test'
        ae.describe_effect(match_name)
        code = ae.run_jsx.call_args.args[0]
        self.assertIn("var mn=" + json.dumps(match_name, ensure_ascii=False) + ";", code)

    def test_live_inventory_is_deduplicated_sorted_and_categorized(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.run_jsx = Mock(  # type: ignore[method-assign]
            return_value=json.dumps(
                [
                    {
                        "displayName": "Gaussian Blur",
                        "matchName": "ADBE Gaussian Blur 2",
                        "category": "Blur",
                        "version": "1.0",
                    },
                    {
                        "displayName": "Gaussian Blur",
                        "matchName": "ADBE Gaussian Blur 2",
                        "category": "Blur",
                        "version": "1.0",
                    },
                    {
                        "displayName": "Hidden",
                        "matchName": "Pseudo/Hidden",
                        "category": "",
                        "version": "0.0",
                    },
                ]
            )
        )
        result = ae.list_available_effects()
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["categories"], {"(hidden)": 1, "Blur": 1})

    def test_search_effects_filters_hidden_and_paginates(self) -> None:
        ae = AEBridge.__new__(AEBridge)
        ae.list_available_effects = Mock(  # type: ignore[method-assign]
            return_value={
                "count": 2,
                "effects": [
                    {
                        "displayName": "Gaussian Blur",
                        "matchName": "ADBE Gaussian Blur 2",
                        "category": "Blur",
                        "version": "1.0",
                    },
                    {
                        "displayName": "Hidden",
                        "matchName": "Pseudo/Hidden",
                        "category": "",
                        "version": "0.0",
                    },
                ],
            }
        )
        result = ae.search_effects("gaussian", limit=10)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["effects"][0]["matchName"], "ADBE Gaussian Blur 2")


class ScriptCatalogTests(unittest.TestCase):
    def test_search_and_readonly_resolution(self) -> None:
        result = search_scripts("诊断")
        self.assertGreaterEqual(result["total"], 1)
        entry = resolve_script("diagnose-bridge")
        self.assertEqual(entry["risk"], "read")
        self.assertIn("app.effects", prepare_script(entry))

    def test_registry_paths_are_confined(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "registry.json").write_text("[]", encoding="utf-8")
            self.assertEqual(load_script_registry(root), [])
            with self.assertRaises(ValueError):
                script_path({"file": "../escape.jsx"}, root)

    def test_declared_custom_modes_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "anchor.jsx").write_text("doThing();", encoding="utf-8")
            (root / "registry.json").write_text(
                json.dumps(
                    [
                        {
                            "slug": "anchor",
                            "name": "Anchor",
                            "file": "anchor.jsx",
                            "modes": ["tl", "mm", "br", "not valid"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            entry = resolve_script("anchor", root)
            self.assertEqual(entry["modes"], ["tl", "mm", "br"])
            self.assertTrue(
                prepare_script(entry, "br", root).startswith('var __mode__ = "br";')
            )
            with self.assertRaises(ValueError):
                prepare_script(entry, "not valid", root)


if __name__ == "__main__":
    unittest.main()
