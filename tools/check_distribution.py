"""Check a built wheel and its installed copy without contacting After Effects.

Run after installing the wheel (not the editable checkout) into the current
interpreter's environment. The child starts outside the repo with isolated imports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path


PROBE = r'''
import asyncio
import importlib.metadata as metadata
import json
import subprocess
import sys
import sysconfig
from pathlib import Path
import ae_bridge
import ae_native_protocol
from ae2claude_mcp import __version__
from ae2claude_mcp.catalog import SCRIPT_ROOT, load_script_registry
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

expected = sys.argv[1]
assert metadata.version("ae2claude") == __version__ == ae_bridge.__version__ == expected
site = Path(sysconfig.get_path("purelib")).resolve()
assert Path(ae_bridge.__file__).resolve().is_relative_to(site), ae_bridge.__file__
entries = load_script_registry()
assert entries, "Installed script registry is empty"
for entry in entries:
    path = (SCRIPT_ROOT / entry["file"]).resolve()
    assert path.is_relative_to(SCRIPT_ROOT.resolve()) and path.is_file(), entry["file"]
entrypoints = {ep.name: ep.value for ep in metadata.distribution("ae2claude").entry_points}
assert entrypoints["ae2claude"] == "ae2claude_mcp.cli:main"
assert entrypoints["ae2claude-mcp"] == "ae2claude_mcp.server:main"
cli = Path(sysconfig.get_path("scripts")) / ("ae2claude.exe" if sys.platform == "win32" else "ae2claude")
output = subprocess.check_output([str(cli), "--version"], encoding="utf-8", timeout=15)
assert output.strip() == "ae2claude " + expected, output

async def discover():
    params = StdioServerParameters(command=sys.executable, args=["-I", "-m", "ae2claude_mcp.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
    tools = {tool.name: tool for tool in result.tools}
    required = {"ae_native_snapshot", "ae_sample_property", "ae_native_keyframes",
                "ae_set_native_keyframes", "ae_layer_transforms", "ae_preview_frames",
                "ae_compare_frames", "ae_script_library", "ae_replay_script"}
    assert required.issubset(tools), required - tools.keys()
    assert tools["ae_set_native_keyframes"].inputSchema["properties"]["dry_run"]["default"] is True
    return sorted(required)

print(json.dumps({"ok": True, "version": expected, "scripts": len(entries),
                  "verifiedTools": asyncio.run(discover()), "liveAE": False}))
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    with zipfile.ZipFile(args.wheel) as wheel:
        names = set(wheel.namelist())
        required = {"ae_bridge.py", "ae_native_protocol.py", "ae2claude_mcp/server.py",
                    "ae2claude_mcp/frame_review.py", "ae2claude_mcp/script_library.py"}
        if not required <= names:
            raise ValueError(f"Wheel is missing modules: {required - names}")
        metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError("Expected exactly one wheel METADATA file")
        metadata = BytesParser().parsebytes(wheel.read(metadata_files[0]))
        if metadata["Version"] != expected:
            raise ValueError(f"Wheel version {metadata['Version']} != {expected}")
    with tempfile.TemporaryDirectory(prefix="ae2claude-wheel-") as directory:
        result = subprocess.run([sys.executable, "-I", "-c", PROBE, expected],
                                cwd=directory, capture_output=True, encoding="utf-8", timeout=90)
    if result.returncode:
        raise RuntimeError(f"Installed wheel smoke check failed:\n{result.stdout}\n{result.stderr}")
    report = json.loads(result.stdout)
    report["wheel"] = args.wheel.name
    report["sha256"] = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
