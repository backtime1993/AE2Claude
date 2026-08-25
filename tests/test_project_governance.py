from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectGovernanceTests(unittest.TestCase):
    def test_single_release_artifact_source(self) -> None:
        self.assertFalse((ROOT / "AE2Claude.aex").exists())
        sync_script = (ROOT / "tools" / "sync-installation.ps1").read_text(encoding="utf-8")
        self.assertIn(r"build\Release\AE2Claude.aex", sync_script)

    def test_pinclicker_is_locked_inside_main_project(self) -> None:
        package = json.loads((ROOT / "extensions" / "pin-clicker" / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "extensions" / "pin-clicker" / "package-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["name"], package["name"])
        self.assertEqual(lock["version"], package["version"])
        readme = (ROOT / "extensions" / "pin-clicker" / "README.md").read_text(encoding="utf-8")
        self.assertIn("AE2Claude/extensions/pin-clicker", readme)
        self.assertNotIn("longterm/AE2ClaudePinClicker/", readme)

    def test_local_and_generated_directories_are_not_versioned(self) -> None:
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for expected in (
            "/vendor/after-effects-sdk/",
            "/artifacts/",
            "/state/",
            "/extensions/pin-clicker/node_modules/",
        ):
            self.assertIn(expected, ignore)

    def test_operational_tools_and_ci_are_present(self) -> None:
        for relative in (
            "tools/bootstrap.ps1",
            "tools/sync-installation.ps1",
            "tools/auto-sync.ps1",
            "tools/clean.ps1",
            "tools/stress_test.py",
            ".github/workflows/ci.yml",
            "docs/PROJECT_GOVERNANCE.md",
            "docs/TESTING.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
