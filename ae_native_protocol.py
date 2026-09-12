"""Shared, dependency-free validation for the structured C++ automation endpoint."""
from __future__ import annotations

import math
from typing import Any

REVISION = "native-automation-20260912"
OPERATIONS = {
    "snapshot": "native_snapshot",
    "sample_property": "native_sample_property",
    "get_keyframes": "native_get_keyframes",
    "set_keyframes": "native_set_keyframes",
    "layer_transforms": "native_layer_transforms",
}


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
    result = {"comp_id": _integer(take("comp_id", 0), "comp_id", 0, 2_147_483_647)}
    if operation == "snapshot":
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
