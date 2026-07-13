from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
