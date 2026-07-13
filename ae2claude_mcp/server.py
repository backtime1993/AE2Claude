"""Official MCP server facade for the native AE2Claude bridge."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent

from .catalog import prepare_script, resolve_script, search_scripts
from .checkpoints import create_checkpoint, list_checkpoints, revert_checkpoint
from .previews import render_preview
from .runtime import (
    approval_mode,
    authorize,
    bridge,
    call_bridge_method,
    classify_bridge_method,
    is_enabled,
    kill_switch_path,
    public_bridge_methods,
    require_enabled,
    set_enabled,
)

mcp = FastMCP(
    "AE2Claude",
    instructions=(
        "Drive the currently running Adobe After Effects instance through the "
        "native AE2Claude bridge. Inspect before mutating, preview visual work, "
        "and create a checkpoint before risky multi-step edits."
    ),
    json_response=True,
)


def _connection_status() -> dict[str, Any]:
    try:
        with bridge() as ae:
            version = ae.run_jsx("app.version")
            project = ae.project_info()
        return {
            "connected": True,
            "aeVersion": version,
            "project": project,
        }
    except Exception as exc:  # diagnostic boundary
        return {"connected": False, "error": str(exc)}


@mcp.tool()
def ae_ping() -> dict[str, Any]:
    """Check MCP safety state and the live native AE bridge connection."""
    return {
        "ok": True,
        "enabled": is_enabled(),
        "approvalMode": approval_mode(),
        "bridge": _connection_status(),
    }


@mcp.tool()
def ae_status() -> dict[str, Any]:
    """Return concise MCP, bridge, and checkpoint configuration status."""
    return {
        "ok": True,
        "enabled": is_enabled(),
        "approvalMode": approval_mode(),
        "killSwitchFile": str(kill_switch_path()),
        "methodCount": len(public_bridge_methods()),
        "bridge": _connection_status(),
    }


@mcp.tool()
def ae_diagnose() -> dict[str, Any]:
    """Run read-only checks across AE, the active project, comp, and bridge."""
    checks: list[dict[str, Any]] = []
    try:
        with bridge() as ae:
            version = ae.run_jsx("app.version")
            checks.append({"name": "bridge", "ok": True, "aeVersion": version})
            project = ae.project_info()
            checks.append({"name": "project", "ok": True, "value": project})
            comp = ae.comp_info()
            checks.append(
                {
                    "name": "activeComp",
                    "ok": bool(comp),
                    "value": comp or None,
                    "hint": None if comp else "Open a composition in After Effects",
                }
            )
    except Exception as exc:
        checks.append({"name": "bridge", "ok": False, "error": str(exc)})
    return {
        "ok": all(item["ok"] for item in checks),
        "enabled": is_enabled(),
        "approvalMode": approval_mode(),
        "checks": checks,
    }


@mcp.tool()
def ae_overview(layer_limit: int = 40) -> dict[str, Any]:
    """Read the current project, active composition, and a bounded layer summary."""
    require_enabled()
    layer_limit = max(1, min(layer_limit, 200))
    with bridge() as ae:
        project = ae.project_info()
        comp = ae.comp_info()
        layers = ae.list_layers() if comp else []
    return {
        "ok": True,
        "project": project,
        "comp": comp or None,
        "layers": layers[:layer_limit],
        "layerCount": len(layers),
        "truncated": len(layers) > layer_limit,
    }


@mcp.tool()
def ae_layers(offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """List active-comp layers with explicit pagination."""
    require_enabled()
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    with bridge() as ae:
        layers = ae.list_layers()
    return {
        "ok": True,
        "offset": offset,
        "limit": limit,
        "total": len(layers),
        "layers": layers[offset : offset + limit],
    }


@mcp.tool()
def ae_effects(
    query: str = "",
    category: str = "",
    include_hidden: bool = False,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Search AE's complete live effect catalog by name, matchName, or category."""
    require_enabled()
    with bridge() as ae:
        return ae.search_effects(
            query=query,
            category=category,
            include_hidden=include_hidden,
            offset=offset,
            limit=limit,
        )


@mcp.tool()
def ae_describe_effect(match_name: str) -> dict[str, Any]:
    """Inspect an installed effect's live property tree and default values."""
    require_enabled()
    with bridge() as ae:
        return ae.describe_effect(match_name)


@mcp.tool()
def ae_add_effect(
    layer_name: str,
    match_name: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Add an installed effect to a layer using its locale-independent matchName."""
    require_enabled()
    authorize("write", confirm=confirm)
    with bridge() as ae:
        result = ae.add_effect_by_match_name(layer_name, match_name)
    return {"ok": True, "layer": layer_name, **result}


@mcp.tool()
def ae_set_effect_property(
    layer_name: str,
    effect_index: int,
    property_match_name: str,
    value: Any,
    time_seconds: float | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Set a live effect property by matchName, optionally at a keyframe time."""
    require_enabled()
    authorize("write", confirm=confirm)
    with bridge() as ae:
        return ae.set_effect_property(
            layer_name,
            effect_index,
            property_match_name,
            value,
            at_time=time_seconds,
        )


@mcp.tool()
def ae_get_effect_property(
    layer_name: str,
    effect_index: int,
    property_match_name: str,
    time_seconds: float | None = None,
) -> dict[str, Any]:
    """Read a live effect property by matchName, optionally at a specific time."""
    require_enabled()
    with bridge() as ae:
        return ae.get_effect_property(
            layer_name,
            effect_index,
            property_match_name,
            at_time=time_seconds,
        )


@mcp.tool()
def ae_scripts(query: str = "", offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Search the bundled JSX library by name, description, note, or tag."""
    require_enabled()
    return search_scripts(query, offset=offset, limit=limit)


@mcp.tool()
def ae_run_script(
    script: str,
    mode: str = "default",
    timeout_ms: int = 60_000,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run one path-confined registered JSX script under its declared safety level."""
    require_enabled()
    entry = resolve_script(script)
    authorize(entry["risk"], confirm=confirm)
    code = prepare_script(entry, mode)
    timeout_ms = max(5_000, min(timeout_ms, 600_000))
    with bridge() as ae:
        raw_result = ae.run_jsx(code, timeout=timeout_ms)
    try:
        result = json.loads(raw_result)
    except (TypeError, json.JSONDecodeError):
        result = raw_result
    return {
        "ok": True,
        "script": entry["slug"],
        "name": entry["name"],
        "risk": entry["risk"],
        "mode": mode,
        "result": result,
    }


@mcp.tool()
def ae_methods() -> dict[str, Any]:
    """List every public native AEBridge method and its safety classification."""
    methods = public_bridge_methods()
    return {
        "ok": True,
        "count": len(methods),
        "methods": [
            {"name": name, "risk": classify_bridge_method(name)} for name in methods
        ],
    }


@mcp.tool()
def ae_call(
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Call any public AEBridge method; destructive calls require confirmation."""
    result = call_bridge_method(method, args, kwargs, confirm=confirm)
    return {
        "ok": True,
        "method": method,
        "risk": classify_bridge_method(method),
        "result": result,
    }


@mcp.tool()
def ae_exec(
    code: str,
    checkpoint_label: str | None = None,
    timeout_ms: int = 60_000,
    confirm: bool = False,
) -> dict[str, Any]:
    """Execute raw ExtendScript. Always treated as destructive and confirm-gated."""
    require_enabled()
    authorize("destructive", confirm=confirm)
    timeout_ms = max(5_000, min(timeout_ms, 600_000))
    with bridge() as ae:
        checkpoint = (
            create_checkpoint(ae, checkpoint_label)
            if checkpoint_label
            else None
        )
        result = ae.run_jsx(code, timeout=timeout_ms)
    return {"ok": True, "checkpoint": checkpoint, "result": result}


@mcp.tool(structured_output=False)
def ae_preview_frame(
    time_seconds: float | None = None,
    max_width: int = 1600,
) -> CallToolResult:
    """Render the active comp frame to PNG and return both metadata and image pixels."""
    require_enabled()
    with bridge() as ae:
        metadata = render_preview(ae, time_seconds, max_width=max_width)
    path = Path(metadata["path"])
    image_data = base64.b64encode(path.read_bytes()).decode("ascii")
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(metadata, ensure_ascii=False),
            ),
            ImageContent(type="image", data=image_data, mimeType="image/png"),
        ],
        structuredContent=metadata,
    )


@mcp.tool()
def ae_checkpoint(label: str = "MCP checkpoint", confirm: bool = False) -> dict[str, Any]:
    """Save the current project and retain a full AEP checkpoint copy."""
    require_enabled()
    authorize("write", confirm=confirm)
    with bridge() as ae:
        return create_checkpoint(ae, label)


@mcp.tool()
def ae_checkpoints(limit: int = 20) -> dict[str, Any]:
    """List checkpoints belonging to the currently open saved project."""
    require_enabled()
    with bridge() as ae:
        return list_checkpoints(ae, limit=limit)


@mcp.tool()
def ae_revert(checkpoint_id: str, confirm: bool = False) -> dict[str, Any]:
    """Destructively restore a checkpoint over the original AEP and reopen it."""
    require_enabled()
    authorize("destructive", confirm=confirm)
    with bridge() as ae:
        return revert_checkpoint(ae, checkpoint_id)


@mcp.tool()
def ae_set_enabled(enabled: bool) -> dict[str, Any]:
    """Enable or disable all MCP-driven AE operations through a local kill switch."""
    path = set_enabled(enabled)
    return {"ok": True, "enabled": is_enabled(), "killSwitchFile": str(path)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
