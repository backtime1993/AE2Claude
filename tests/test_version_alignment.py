from __future__ import annotations

import json
import re
import tomllib
import unittest
from pathlib import Path

from ae_bridge import __version__ as bridge_version
from ae2claude_mcp import __version__ as mcp_version


ROOT = Path(__file__).resolve().parents[1]


def _constant(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if not match:
        raise AssertionError(f"Missing {name} in {path}")
    return match.group(1)


class VersionAlignmentTests(unittest.TestCase):
    def test_all_python_surfaces_share_one_version(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        expected = project["project"]["version"]
        self.assertRegex(expected, r"^\d+\.\d+\.\d+(?:rc\d+)?$")
        self.assertEqual(mcp_version, expected)
        self.assertEqual(bridge_version, expected)
        self.assertEqual(_constant(ROOT / "ae2claude", "CLI_VERSION"), expected)
        self.assertEqual(_constant(ROOT / "ae2claude_server.py", "BRIDGE_VERSION"), expected)

    def test_lock_plugin_and_readme_match_package_version(self) -> None:
        expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        package = next(item for item in lock["package"] if item["name"] == "ae2claude")
        self.assertEqual(package["version"], expected)
        manifest = json.loads((ROOT / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        # Python uses PEP 440 (4.4.0rc1); the plugin uses SemVer (4.4.0-rc.1).
        semver = re.sub(r"rc(\d+)$", r"-rc.\1", expected)
        self.assertEqual(manifest["version"], semver)
        self.assertIn(f"AE2Claude {expected}", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_deployer_uses_release_build_not_stale_root_binary(self) -> None:
        deployer = (ROOT / "deploy.bat").read_text(encoding="utf-8")
        sync_script = (ROOT / "tools" / "sync-installation.ps1").read_text(encoding="utf-8")
        self.assertIn(r"tools\sync-installation.ps1", deployer)
        self.assertIn(r"build\Release\AE2Claude.aex", sync_script)
        self.assertIn("Get-FileHash", sync_script)
        self.assertNotIn('copy /Y "%~dp0AE2Claude.aex"', deployer)

    def test_read_only_cli_calls_do_not_ensure_a_comp(self) -> None:
        cli = (ROOT / "ae2claude").read_text(encoding="utf-8")
        self.assertIn('classify_bridge_method(args[1]) != "read"', cli)


if __name__ == "__main__":
    unittest.main()
