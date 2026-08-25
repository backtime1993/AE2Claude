from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

from ae_bridge import AEBridge
from ae2claude_mcp import __version__


LIVE = os.environ.get("AE2CLAUDE_LIVE_TEST") == "1"
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(LIVE, "set AE2CLAUDE_LIVE_TEST=1 with AE running")
class LiveAE27Tests(unittest.TestCase):
    def test_native_bridge_reports_aligned_artifact(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:8089/health", timeout=5) as response:
            health = json.loads(response.read())
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["bridge_version"], __version__)
        self.assertTrue(health["module_available"])
        self.assertTrue(health["plugin_artifact"]["present"])
        self.assertRegex(health["plugin_artifact"]["sha256"], r"^[0-9a-f]{64}$")

    def test_after_effects_27_read_path(self) -> None:
        with AEBridge() as ae:
            version = str(ae.run_jsx("app.version"))
            project = ae.project_info()
        self.assertTrue(version.startswith("27."), version)
        self.assertIsInstance(project, dict)

    def test_pinclicker_reports_ae_window_and_version(self) -> None:
        with urllib.request.urlopen("http://127.0.0.1:8891/health", timeout=5) as response:
            health = json.loads(response.read())
        self.assertTrue(health["ok"])
        self.assertEqual(health["extension_version"], "0.6.0")
        self.assertTrue(str(health["ae"]["version"]).startswith("27."))
        self.assertNotIn("error", health["window"])
        self.assertTrue(str(health["window"]["class"]).startswith("AE_CApplication"))

    def test_cli_read_call_does_not_create_default_comp(self) -> None:
        with AEBridge() as ae:
            before = int(ae.run_jsx("app.project.numItems"))
        if before != 0:
            self.skipTest("requires an empty unsaved AE project")

        completed = subprocess.run(
            [sys.executable, str(ROOT / "ae2claude"), "call", "project_info"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        with AEBridge() as ae:
            after = int(ae.run_jsx("app.project.numItems"))
        self.assertEqual(after, 0)


if __name__ == "__main__":
    unittest.main()
