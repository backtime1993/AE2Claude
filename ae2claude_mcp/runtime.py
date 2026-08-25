"""Shared runtime, safety, and bridge helpers for AE2Claude MCP."""
from __future__ import annotations

import inspect
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from ae_bridge import AEBridge

Risk = Literal["read", "write", "destructive"]
ApprovalMode = Literal["readonly", "manual", "auto", "bypass"]

VALID_APPROVAL_MODES: set[str] = {"readonly", "manual", "auto", "bypass"}

READ_METHODS = {
    "comp_info",
    "project_info",
    "render_queue_info",
    "get_selected_layers",
}
READ_PREFIXES = (
    "get_",
    "list_",
    "describe_",
    "enumerate_",
    "search_",
    "sample_",
    "approximate_",
    "detect_",
)
DESTRUCTIVE_METHODS = {
    "clear_render_queue",
    "exec_jsx_file",
    "remove_layer",
    "remove_mask",
    "remove_render_item",
    "remove_puppet_pins",
    "remove_solid_background_layers",
    "run_jsx",
    "run_jsx_checked",
    "start_render",
}


class SafetyError(PermissionError):
    """Raised when the active MCP safety policy blocks an operation."""


def approval_mode() -> ApprovalMode:
    value = os.environ.get("AE2CLAUDE_APPROVAL_MODE", "auto").strip().lower()
    if value not in VALID_APPROVAL_MODES:
        value = "manual"
    return value  # type: ignore[return-value]


def classify_bridge_method(name: str) -> Risk:
    if name in DESTRUCTIVE_METHODS:
        return "destructive"
    if name in READ_METHODS or name.startswith(READ_PREFIXES):
        return "read"
    return "write"


def authorize(risk: Risk, *, confirm: bool = False) -> None:
    """Enforce a deterministic cross-client approval policy.

    manual requires explicit confirmation for every write. auto permits ordinary
    writes but still requires confirmation for destructive operations.
    """
    mode = approval_mode()
    if mode == "bypass" or risk == "read":
        return
    if mode == "readonly":
        raise SafetyError("AE2Claude MCP is in read-only mode")
    if mode == "manual" and not confirm:
        raise SafetyError("This write requires confirm=true in manual mode")
    if mode == "auto" and risk == "destructive" and not confirm:
        raise SafetyError("This destructive operation requires confirm=true")


def kill_switch_path() -> Path:
    configured = os.environ.get("AE2CLAUDE_KILL_SWITCH_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path(tempfile.gettempdir()) / "ae2claude" / "mcp-disabled"


def is_enabled() -> bool:
    return not kill_switch_path().exists()


def set_enabled(enabled: bool) -> Path:
    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if enabled:
        path.unlink(missing_ok=True)
    else:
        path.write_text("disabled\n", encoding="utf-8")
    return path


def require_enabled() -> None:
    if not is_enabled():
        raise SafetyError(
            f"AE2Claude MCP kill switch is active: {kill_switch_path()}"
        )


def bridge() -> AEBridge:
    port = int(os.environ.get("AE2CLAUDE_PORT", "8089"))
    timeout = int(os.environ.get("AE2CLAUDE_TIMEOUT", "30"))
    return AEBridge(port=port, timeout=timeout)


def public_bridge_methods() -> list[str]:
    return sorted(
        name
        for name, member in inspect.getmembers(AEBridge, predicate=callable)
        if not name.startswith("_") and name not in {"close", "reconnect"}
    )


def call_bridge_method(
    method: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
    *,
    confirm: bool = False,
) -> Any:
    require_enabled()
    if method not in public_bridge_methods():
        raise ValueError(f"Unknown or private AEBridge method: {method}")
    authorize(classify_bridge_method(method), confirm=confirm)
    with bridge() as ae:
        fn = getattr(ae, method)
        return fn(*(args or []), **(kwargs or {}))
