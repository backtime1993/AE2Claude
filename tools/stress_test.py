"""Bounded, project-safe AE2Claude pressure test.

The write phase only runs when After Effects has an empty, unsaved project.
All generated comps and layers are removed before the phase returns.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ae_bridge import AEBridge  # noqa: E402
from ae2claude_mcp.server import ae_ping  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def summarize(name: str, timings: list[float], errors: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "requests": len(timings) + len(errors),
        "passed": len(timings),
        "failed": len(errors),
        "latencyMs": {
            "mean": round(statistics.fmean(timings), 3) if timings else None,
            "p50": round(percentile(timings, 0.50), 3) if timings else None,
            "p95": round(percentile(timings, 0.95), 3) if timings else None,
            "max": round(max(timings), 3) if timings else None,
        },
        "errors": errors[:20],
    }


def run_parallel(
    name: str,
    count: int,
    workers: int,
    operation: Callable[[], None],
) -> dict[str, Any]:
    timings: list[float] = []
    errors: list[str] = []

    def measured() -> float:
        started = time.perf_counter()
        operation()
        return (time.perf_counter() - started) * 1000

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(measured) for _ in range(count)]
        for future in as_completed(futures):
            try:
                timings.append(future.result())
            except Exception as exc:  # pressure-test aggregation boundary
                errors.append(f"{type(exc).__name__}: {exc}")
    return summarize(name, timings, errors)


def get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read())


def post_jsx(source: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "http://127.0.0.1:8089/jsx",
        data=source.encode("utf-8"),
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())


def process_snapshot() -> list[dict[str, Any]]:
    script = (
        "Get-Process -Name 'AfterFX*' -ErrorAction SilentlyContinue | "
        "Select-Object Id,ProcessName,WorkingSet64,PrivateMemorySize64,Handles,StartTime | "
        "ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    value = json.loads(completed.stdout)
    return value if isinstance(value, list) else [value]


def run_write_cycles(cycles: int, layers_per_cycle: int) -> dict[str, Any]:
    probe = """
(function () {
    return JSON.stringify({
        file: app.project.file ? app.project.file.fsName : null,
        items: app.project.numItems
    });
}())
"""
    with AEBridge(timeout=30) as ae:
        project_state = json.loads(ae.run_jsx(probe))
        if project_state["file"] is not None or int(project_state["items"]) != 0:
            return {
                "ok": False,
                "skipped": True,
                "reason": "write pressure requires an empty, unsaved AE project",
                "projectState": project_state,
            }

        jsx = f"""
(function () {{
    var cycles = {cycles};
    var layersPerCycle = {layers_per_cycle};
    var createdLayers = 0;
    var checksum = 0;
    app.beginUndoGroup("AE2Claude bounded pressure test");
    try {{
        for (var cycle = 0; cycle < cycles; cycle++) {{
            var comp = null;
            try {{
                comp = app.project.items.addComp(
                    "__AE2CLAUDE_STRESS_" + cycle,
                    640,
                    360,
                    1,
                    3,
                    30
                );
                for (var index = 0; index < layersPerCycle; index++) {{
                    var layer = comp.layers.addText("stress_" + cycle + "_" + index);
                    layer.property("ADBE Transform Group").property("ADBE Position")
                        .setValue([32 + (index % 10) * 60, 32 + (index % 5) * 60]);
                    var opacity = layer.property("ADBE Transform Group").property("ADBE Opacity");
                    opacity.setValueAtTime(0, 0);
                    opacity.setValueAtTime(1, 100);
                    opacity.setValueAtTime(2, 50);
                    checksum += opacity.numKeys + layer.index;
                    createdLayers++;
                }}
                if (comp.numLayers !== layersPerCycle) {{
                    throw new Error("layer count mismatch");
                }}
            }} finally {{
                if (comp !== null) {{
                    comp.remove();
                }}
            }}
        }}
    }} finally {{
        app.endUndoGroup();
    }}
    return JSON.stringify({{
        ok: app.project.numItems === 0,
        cycles: cycles,
        layersPerCycle: layersPerCycle,
        createdLayers: createdLayers,
        checksum: checksum,
        remainingItems: app.project.numItems
    }});
}}())
"""
        started = time.perf_counter()
        result = json.loads(ae.run_jsx(jsx, timeout=max(60_000, cycles * layers_per_cycle * 250)))
        result["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
        result["skipped"] = False
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--write-cycles", type=int, default=12)
    parser.add_argument("--layers-per-cycle", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.requests < 1 or args.workers < 1:
        parser.error("requests and workers must be positive")
    if args.write_cycles < 0 or args.layers_per_cycle < 1:
        parser.error("invalid write pressure bounds")

    output = args.output or (
        ROOT / "artifacts" / "stress" / f"stress-{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)

    before = process_snapshot()

    def bridge_health() -> None:
        payload = get_json("http://127.0.0.1:8089/health")
        if payload.get("status") != "ok" or not payload.get("module_available"):
            raise RuntimeError(f"bad bridge health: {payload}")

    def pin_health() -> None:
        payload = get_json("http://127.0.0.1:8891/health")
        if not payload.get("ok") or payload.get("extension_version") != "0.6.0":
            raise RuntimeError(f"bad PinClicker health: {payload}")

    def jsx_read() -> None:
        payload = post_jsx("app.version")
        if not payload.get("ok") or not str(payload.get("result", "")).startswith("27."):
            raise RuntimeError(f"bad JSX response: {payload}")

    suites = [
        run_parallel("bridge-health", args.requests, args.workers, bridge_health),
        run_parallel("pinclicker-health", args.requests, args.workers, pin_health),
        run_parallel("jsx-read", args.requests, args.workers, jsx_read),
    ]

    mcp_timings: list[float] = []
    mcp_errors: list[str] = []
    for _ in range(max(20, args.requests // 4)):
        started = time.perf_counter()
        try:
            payload = ae_ping()
            if not payload.get("ok") or not payload.get("bridge", {}).get("connected"):
                raise RuntimeError(f"bad MCP facade response: {payload}")
            mcp_timings.append((time.perf_counter() - started) * 1000)
        except Exception as exc:
            mcp_errors.append(f"{type(exc).__name__}: {exc}")
    suites.append(summarize("mcp-ae-ping", mcp_timings, mcp_errors))

    write_result = run_write_cycles(args.write_cycles, args.layers_per_cycle)
    after = process_snapshot()
    failures = sum(int(suite["failed"]) for suite in suites)
    write_failed = not write_result.get("ok", False)
    report = {
        "ok": failures == 0 and not write_failed,
        "timestamp": datetime.now().astimezone().isoformat(),
        "bounds": {
            "requestsPerReadSuite": args.requests,
            "workers": args.workers,
            "writeCycles": args.write_cycles,
            "layersPerCycle": args.layers_per_cycle,
        },
        "processBefore": before,
        "processAfter": after,
        "suites": suites,
        "writePressure": write_result,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report["ok"], "report": str(output), "suites": suites, "writePressure": write_result}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
