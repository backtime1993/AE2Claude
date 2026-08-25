from __future__ import annotations

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
        self.assertEqual(expected, "4.2.0")
        self.assertEqual(mcp_version, expected)
        self.assertEqual(bridge_version, expected)
        self.assertEqual(_constant(ROOT / "ae2claude", "CLI_VERSION"), expected)
        self.assertEqual(_constant(ROOT / "ae2claude_server.py", "BRIDGE_VERSION"), expected)

    def test_deployer_uses_release_build_not_stale_root_binary(self) -> None:
        deployer = (ROOT / "deploy.bat").read_text(encoding="utf-8")
        self.assertIn(r"build\Release\AE2Claude.aex", deployer)
        self.assertNotIn('copy /Y "%~dp0AE2Claude.aex"', deployer)
        self.assertIn("fc /B", deployer)

    def test_read_only_cli_calls_do_not_ensure_a_comp(self) -> None:
        cli = (ROOT / "ae2claude").read_text(encoding="utf-8")
        self.assertIn('classify_bridge_method(args[1]) != "read"', cli)


if __name__ == "__main__":
    unittest.main()
