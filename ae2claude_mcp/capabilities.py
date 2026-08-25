"""Self-describing Agent API contract shared by MCP and the CLI."""
from __future__ import annotations

import inspect
import types
from typing import Any, get_args, get_origin

from ae_bridge import AEBridge

from .runtime import classify_bridge_method, public_bridge_methods

AGENT_PROTOCOL = "ae2claude.agent/v1"


def _json_type(annotation: Any) -> dict[str, Any]:
    if annotation in (inspect.Signature.empty, Any):
        return {}
    if annotation in (str,):
        return {"type": "string"}
    if annotation in (int,):
        return {"type": "integer"}
    if annotation in (float,):
        return {"type": "number"}
    if annotation in (bool,):
        return {"type": "boolean"}
    if annotation in (dict,):
        return {"type": "object"}
    if annotation in (list, tuple):
        return {"type": "array"}
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin in (list, tuple):
        return {"type": "array", "items": _json_type(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object"}
    if origin in (types.UnionType, getattr(__import__("typing"), "Union")):
        schemas = [_json_type(arg) for arg in args if arg is not type(None)]
        schema = schemas[0] if len(schemas) == 1 else {"anyOf": schemas}
        if len(schemas) != len(args):
            schema["nullable"] = True
        return schema
    return {"title": str(annotation).replace("typing.", "")}


def _category(name: str) -> str:
    for prefix, category in (
        (("get_", "list_", "describe_", "search_", "inspect_"), "inspect"),
        (("render_", "start_render", "add_to_render"), "render"),
        (("add_effect", "set_effect", "enumerate_effect"), "effects"),
        (("add_puppet", "set_puppet", "list_puppet", "auto_place_puppet"), "puppet"),
        (("add_text", "set_text", "animate_text"), "text"),
        (("add_shape",), "shape"),
        (("add_mask", "set_mask", "remove_mask", "animate_mask"), "mask"),
        (("property_", "get_property", "set_property", "inspect_properties"), "property"),
        (("create_", "add_", "set_", "remove_", "duplicate_", "rename_"), "edit"),
    ):
        if name.startswith(prefix):
            return category
    return "core"


def method_descriptor(name: str) -> dict[str, Any]:
    member = getattr(AEBridge, name)
    signature = inspect.signature(member)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for parameter in signature.parameters.values():
        if parameter.name == "self" or parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        schema = _json_type(parameter.annotation)
        if parameter.default is inspect.Signature.empty:
            required.append(parameter.name)
        else:
            schema["default"] = parameter.default
        properties[parameter.name] = schema
    doc = inspect.getdoc(member) or ""
    return {
        "name": name,
        "category": _category(name),
        "risk": classify_bridge_method(name),
        "description": doc.splitlines()[0] if doc else "",
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def capabilities(query: str = "", category: str = "") -> dict[str, Any]:
    query = query.casefold().strip()
    category = category.casefold().strip()
    methods = []
    for name in public_bridge_methods():
        descriptor = method_descriptor(name)
        if query and query not in (
            name + " " + descriptor["description"] + " " + descriptor["category"]
        ).casefold():
            continue
        if category and descriptor["category"].casefold() != category:
            continue
        methods.append(descriptor)
    return {
        "ok": True,
        "protocol": AGENT_PROTOCOL,
        "features": {
            "stableLayerIds": True,
            "matchNamePropertyPaths": True,
            "zeroBasedIndexedPathSteps": True,
            "singleDispatchPropertyBatch": True,
            "dryRun": True,
            "singleUndoGroupPropertyBatch": True,
            "genericBatchUndoMode": "per-operation",
            "resultReferences": True,
            "backgroundJobs": True,
            "cooperativeCancellation": True,
            "eventCursor": True,
            "maxBatchOperations": 256,
        },
        "propertyBackends": {
            "native": {
                "name": "aegp-single-dispatch",
                "types": ["scalar", "2d", "2d_spatial", "3d", "3d_spatial", "color"],
            },
            "fallback": {"name": "jsx-single-dispatch", "types": ["ae-scriptable"]},
        },
        "methodCount": len(methods),
        "methods": methods,
    }
