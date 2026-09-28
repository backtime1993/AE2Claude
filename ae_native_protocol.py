"""Shared, dependency-free validation for the structured C++ automation endpoint."""
from __future__ import annotations

import math
from typing import Any

REVISION = "native-automation-20260926"
OPERATIONS = {
    "snapshot": "native_snapshot",
    "sample_property": "native_sample_property",
    "sample_properties": "native_sample_properties",
    "footage_inventory": "native_footage_inventory",
    "get_keyframes": "native_get_keyframes",
    "set_keyframes": "native_set_keyframes",
    "set_keyframe_ease": "native_set_keyframe_ease",
    "set_layer_controls": "native_set_layer_controls",
    "layer_transforms": "native_layer_transforms",
}

LAYER_FLAGS = frozenset({"enabled", "audio_active", "effects_active", "motion_blur", "shy", "solo", "guide", "adjustment"})
BLEND_MODES = frozenset({"normal", "add", "multiply", "screen", "overlay", "difference"})


def operation_contracts(available=None) -> dict:
    """Static discovery without starting AE. Availability comes from live health."""
    limits = {
        "snapshot": {"max_items": 2000, "max_layers": 2000},
        "sample_property": {"times": 2048},
        "sample_properties": {"properties": 64, "times": 2048, "total_samples": 4096},
        "footage_inventory": {"max_items": 2000},
        "get_keyframes": {"max_keys": 4096},
        "set_keyframes": {"keyframes": 4096},
        "set_keyframe_ease": {"keyframes": 4096},
        "set_layer_controls": {"changes": 256},
        "layer_transforms": {"layer_ids": 64, "times": 64, "total_matrices": 1024},
    }
    return {name: {"risk": "write" if name.startswith("set_") else "read", "limits": limits[name],
                   "dispatches": 1, "dryRunDefault": True if name.startswith("set_") else None,
                   "undo": "single-group" if name.startswith("set_") else None}
            for name in OPERATIONS if available is None or name in available}


def _write_options(take, result, default):
    result["dry_run"] = _boolean(take("dry_run", True), "dry_run")
    name = take("undo_name", default)
    if not isinstance(name, str) or not 1 <= len(name.encode("utf-8")) <= 200 or "\0" in name:
        raise ValueError("undo_name must be 1..200 UTF-8 bytes without NUL")
    result["undo_name"] = name


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be boolean")
    return value


def _number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("values must be finite numbers, not booleans")
    return float(value)


def _time(value: Any) -> float:
    value = _number(value)
    if abs(value) > 86400:
        raise ValueError("time must be within +/-86400 seconds")
    return value


def quantized_time(seconds: float) -> float:
    """Match C++ llround and the signed 32-bit A_Time numerator."""
    scale = 1_000_000
    while abs(seconds) * scale > 2_147_483_646:
        scale //= 10
    return math.copysign(math.floor(abs(seconds) * scale + 0.5), seconds) / scale


def _list(value: Any, name: str, maximum: int) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValueError(f"{name} must contain 1..{maximum} entries")
    return value


def _path(value: Any) -> list[str | int]:
    result = []
    for step in _list(value, "path", 64):
        if type(step) is int:
            result.append(_integer(step, "path index", 0, 2_147_483_647))
        elif isinstance(step, str) and 0 < len(step.encode("utf-8")) <= 255 and "\0" not in step:
            result.append(step)
        else:
            raise ValueError("path requires matchNames or zero-based integer indices")
    return result


def normalize_request(operation: str, arguments: dict) -> dict:
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError("unknown_native_operation")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    remaining = dict(arguments)
    def take(name: str, default: Any = None) -> Any:
        return remaining.pop(name, default)
    result = {} if operation == "footage_inventory" else {"comp_id": _integer(take("comp_id", 0), "comp_id", 0, 2_147_483_647)}
    if operation == "footage_inventory":
        result.update(offset=_integer(take("offset", 0), "offset", 0, 100000),
                      max_items=_integer(take("max_items", 500), "max_items", 1, 2000),
                      include_proxy=_boolean(take("include_proxy", True), "include_proxy"))
    elif operation == "sample_properties":
        properties = []
        for prop in _list(take("properties"), "properties", 64):
            if not isinstance(prop, dict) or set(prop) != {"layer_id", "path"}:
                raise ValueError('each property requires exactly layer_id and path')
            properties.append({"layer_id": _integer(prop['layer_id'], 'layer_id', 1, 2_147_483_647),
                               "path": _path(prop['path'])})
        result['times'] = [_time(t) for t in _list(take('times'), 'times', 2048)]
        if len(properties) * len(result['times']) > 4096:
            raise ValueError('at most 4096 property/time samples per call')
        result['properties'] = properties
        result['pre_expression'] = _boolean(take('pre_expression', False), 'pre_expression')
    elif operation == "set_layer_controls":
        changes, seen = [], set()
        for change in _list(take("changes"), "changes", 256):
            if not isinstance(change, dict) or set(change) - {"layer_id", "flags", "blend_mode"}:
                raise ValueError("layer change requires layer_id and flags and/or blend_mode")
            layer = _integer(change.get("layer_id"), "layer_id", 1, 2_147_483_647)
            if layer in seen:
                raise ValueError("duplicate layer_id")
            seen.add(layer)
            flags = change.get("flags", {})
            if not isinstance(flags, dict) or set(flags) - LAYER_FLAGS:
                raise ValueError("unsupported layer flags")
            row = {"layer_id": layer, "flags": {k: _boolean(v, k) for k, v in flags.items()}}
            if "blend_mode" in change:
                mode = change["blend_mode"]
                if not isinstance(mode, str) or mode not in BLEND_MODES:
                    raise ValueError("unsupported blend_mode")
                row["blend_mode"] = mode
            if not flags and "blend_mode" not in row:
                raise ValueError("empty layer change")
            changes.append(row)
        result["changes"] = changes
        _write_options(take, result, "AE2Claude Native Layer Controls")
    elif operation == "snapshot":
        result.update(max_items=_integer(take("max_items", 500), "max_items", 1, 2000),
                      max_layers=_integer(take("max_layers", 500), "max_layers", 1, 2000))
    elif operation == "layer_transforms":
        result["layer_ids"] = [_integer(v, "layer_id", 1, 2_147_483_647)
                               for v in _list(take("layer_ids"), "layer_ids", 64)]
        result["times"] = [_time(t) for t in _list(take("times"), "times", 64)]
        if len(result["layer_ids"]) * len(result["times"]) > 1024:
            raise ValueError("at most 1024 matrices per call")
    else:
        result["layer_id"] = _integer(take("layer_id"), "layer_id", 1, 2_147_483_647)
        result["path"] = _path(take("path"))
        if operation == "sample_property":
            result["times"] = [_time(t) for t in _list(take("times"), "times", 2048)]
            result["pre_expression"] = _boolean(take("pre_expression", False), "pre_expression")
        elif operation == "get_keyframes":
            result["start_index"] = _integer(take("start_index", 0), "start_index", 0, 1_000_000)
            result["max_keys"] = _integer(take("max_keys", 1000), "max_keys", 1, 4096)
        elif operation == "set_keyframe_ease":
            frames, seen = [], set()
            for frame in _list(take("keyframes"), "keyframes", 4096):
                if not isinstance(frame, dict) or set(frame) != {"index", "temporal_ease"}:
                    raise ValueError("ease key requires exactly index and temporal_ease")
                index = _integer(frame["index"], "index", 0, 1_000_000)
                if index in seen:
                    raise ValueError("duplicate key index")
                seen.add(index)
                ease = []
                for dimension in _list(frame["temporal_ease"], "temporal_ease", 4):
                    if not isinstance(dimension, list) or len(dimension) != 4:
                        raise ValueError("ease dimension requires [inSpeed,inInfluence,outSpeed,outInfluence]")
                    values = [_number(v) for v in dimension]
                    if not all(0.001 <= values[i] <= 1 for i in (1, 3)):
                        raise ValueError("native influence is a fraction in 0.001..1")
                    ease.append(values)
                frames.append({"index": index, "temporal_ease": ease})
            result["keyframes"] = frames
            _write_options(take, result, "AE2Claude Native Keyframe Ease")
        else:
            frames = []
            previous = -math.inf
            for frame in _list(take("keyframes"), "keyframes", 4096):
                if not isinstance(frame, dict) or set(frame) != {"time", "value"}:
                    raise ValueError("each keyframe requires exactly time and value")
                t = _time(frame["time"])
                actual = quantized_time(t)
                if actual <= previous:
                    raise ValueError("keyframe times must increase after native time quantization")
                previous = actual
                value = frame["value"]
                if isinstance(value, list):
                    if not 2 <= len(value) <= 4:
                        raise ValueError("vector requires 2..4 values; colors use RGBA")
                    value = [_number(v) for v in value]
                else:
                    value = _number(value)
                frames.append({"time": t, "value": value})
            result["keyframes"] = frames
            result["dry_run"] = _boolean(take("dry_run", True), "dry_run")
            undo_name = take("undo_name", "AE2Claude Native Keyframes")
            if not isinstance(undo_name, str) or not 1 <= len(undo_name.encode("utf-8")) <= 200 or "\0" in undo_name:
                raise ValueError("undo_name must be 1..200 UTF-8 bytes without NUL")
            result["undo_name"] = undo_name
    if remaining:
        raise ValueError("unknown native arguments: " + ", ".join(sorted(remaining)))
    return result
