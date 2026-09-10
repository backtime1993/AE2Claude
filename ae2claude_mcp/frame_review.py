"""Bounded contact sheets and pixel comparisons built on the existing preview path.

Capture references are persistent, hash-checked manifests; no arbitrary path reads.
Metrics describe decoded preview pixels, not HDR/source scene values.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageStat

from .previews import preview_root, render_preview
from .runtime import require_enabled


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(image: Image.Image, prefix: str) -> dict[str, Any]:
    path = preview_root() / f"{prefix}-{uuid.uuid4().hex}.png"
    image.save(path, format="PNG")
    return {"path": str(path), "width": image.width, "height": image.height,
            "sha256": _digest(path), "sizeBytes": path.stat().st_size}


def review_times(times: list[float] | None, start: float | None,
                 end: float | None, count: int) -> list[float]:
    if times is not None:
        if start is not None or end is not None:
            raise ValueError("Use times OR start/end/count")
        values = [float(t) for t in times]
    else:
        if start is None or end is None or not 2 <= count <= 16:
            raise ValueError("A range requires start, end and count between 2 and 16")
        if end <= start:
            raise ValueError("end must be greater than start")
        values = [start + (end - start) * i / (count - 1) for i in range(count)]
    if not 1 <= len(values) <= 16 or any(not math.isfinite(t) or t < 0 for t in values):
        raise ValueError("Provide 1-16 finite, nonnegative sample times")
    return values


def capture_frames(ae: Any, *, times: list[float] | None = None,
                   start: float | None = None, end: float | None = None,
                   count: int = 6, max_width: int = 1600,
                   grid_max_side: int = 1600) -> dict[str, Any]:
    values = review_times(times, start, end, count)
    if not 320 <= max_width <= 4096 or not 320 <= grid_max_side <= 2048:
        raise ValueError("max_width must be 320-4096; grid_max_side must be 320-2048")
    frames = []
    deadline = time.monotonic() + 110
    for t in values:
        require_enabled()
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms < 5000:
            raise TimeoutError("Review time budget exhausted; request fewer frames")
        frame = render_preview(ae, t, max_width=max_width, timeout_ms=remaining_ms)
        if frames and (frame["compId"] != frames[0]["compId"] or
                       (frame["width"], frame["height"]) !=
                       (frames[0]["width"], frames[0]["height"])):
            raise RuntimeError("Active composition changed during capture; discard this review")
        frames.append(frame)
    columns = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)
    cell_w = grid_max_side // columns
    cell_h = grid_max_side // rows
    # Keep the source aspect ratio; cell coordinates refer to the returned grid.
    image_h = max(1, cell_h - 26)
    aspect = frames[0]["previewHeight"] / frames[0]["previewWidth"]
    cell_h = min(cell_h, math.ceil(cell_w * aspect) + 26)
    image_h = cell_h - 26
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#202024")
    draw = ImageDraw.Draw(sheet)
    cells = []
    for index, frame in enumerate(frames):
        x, y = (index % columns) * cell_w, (index // columns) * cell_h
        with Image.open(frame["path"]) as source:
            tile = source.convert("RGBA")
        tile.thumbnail((cell_w, image_h), Image.Resampling.LANCZOS)
        px, py = x + (cell_w - tile.width) // 2, y + 26 + (image_h - tile.height) // 2
        sheet.paste(tile, (px, py), tile)
        draw.text((x + 6, y + 6), f"{index + 1} | {frame['time']:.4f}s", fill="white")
        cells.append({"index": index, "time": frame["time"], "x": px, "y": py,
                      "width": tile.width, "height": tile.height})
    grid = {**_artifact(sheet, "grid"), "columns": columns, "rows": rows, "cells": cells}
    capture_id = uuid.uuid4().hex
    result = {"ok": True, "captureId": capture_id, "frames": frames, "grid": grid,
              "note": "Sequential samples; not an atomic timeline snapshot. Preview pixels may be resized and converted to 8-bit."}
    manifest = preview_root() / f"capture-{capture_id}.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def stored_frame(capture_id: str, index: int) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", capture_id):
        raise ValueError("Invalid capture ID")
    root = preview_root().resolve()
    manifest = root / f"capture-{capture_id}.json"
    if manifest.resolve().parent != root:
        raise ValueError("Capture manifest escaped preview root")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if not 0 <= index < len(record["frames"]):
        raise ValueError("Frame index is out of range (zero-based)")
    frame = record["frames"][index]
    path = Path(frame["path"]).resolve()
    if path.parent != root or path.suffix.lower() != ".png":
        raise ValueError("Frame path escaped preview root")
    if _digest(path) != frame["sha256"]:
        raise ValueError("Captured frame changed on disk; capture it again")
    return frame


def compare_frames(capture_a: str, index_a: int, capture_b: str, index_b: int,
                   threshold: int = 8) -> dict[str, Any]:
    if not 0 <= threshold <= 255:
        raise ValueError("threshold must be 0-255")
    a = stored_frame(capture_a, index_a)
    b = stored_frame(capture_b, index_b)
    with Image.open(a["path"]) as image:
        left = image.convert("RGBA")
    with Image.open(b["path"]) as image:
        right = image.convert("RGBA")
    if left.size != right.size:
        raise ValueError("Frame dimensions differ; recapture using the same max_width")
    # Ignore invisible RGB noise: compare appearance over black plus alpha.
    black = Image.new("RGBA", left.size, (0, 0, 0, 255))
    visible_a = Image.alpha_composite(black, left).convert("RGB")
    visible_b = Image.alpha_composite(black, right).convert("RGB")
    delta = ImageChops.difference(visible_a, visible_b)
    channels = list(delta.split()) + [ImageChops.difference(left.getchannel("A"), right.getchannel("A"))]
    maximum = channels[0]
    for channel in channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    mask = maximum.point(lambda value: 255 if value > threshold else 0)
    changed = mask.histogram()[255]
    total = left.width * left.height
    heatmap = Image.merge("RGB", (maximum, Image.new("L", left.size), Image.new("L", left.size)))
    side = Image.new("RGB", (left.width * 2, left.height + 26), "#202024")
    side.paste(visible_a, (0, 26))
    side.paste(visible_b, (left.width, 26))
    draw = ImageDraw.Draw(side)
    draw.text((6, 6), f"A | {a['time']:.4f}s", fill="white")
    draw.text((left.width + 6, 6), f"B | {b['time']:.4f}s", fill="white")
    return {"ok": True, "a": {"captureId": capture_a, "index": index_a},
            "b": {"captureId": capture_b, "index": index_b}, "threshold": threshold,
            "changedPixels": changed, "totalPixels": total, "changedRatio": changed / total,
            "meanAbsDiff": sum(ImageStat.Stat(c).mean[0] for c in channels) / 4,
            "maxAbsDiff": maximum.getextrema()[1], "bbox": mask.getbbox(),
            "metricWidth": left.width, "metricHeight": left.height,
            "metricSpace": "8-bit preview pixels: RGB appearance over black plus alpha; bbox is [left,top,right,bottom), null if unchanged",
            "diff": _artifact(heatmap, "diff"), "sideBySide": _artifact(side, "compare")}


def inline_png(path: str, max_side: int = 2048, max_bytes: int = 3_000_000) -> bytes:
    """Bound response bytes without altering full-size artifacts on disk."""
    with Image.open(path) as source:
        image = source.copy()
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    while True:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        data = stream.getvalue()
        if len(data) <= max_bytes:
            return data
        if max(image.size) <= 256:
            raise ValueError("Preview cannot fit inline image budget; use artifact path")
        image.thumbnail((max(1, int(image.width * .75)), max(1, int(image.height * .75))), Image.Resampling.LANCZOS)
