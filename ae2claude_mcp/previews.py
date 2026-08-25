"""Managed real-comp frame previews for MCP image responses."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ae_bridge import AEBridge
from PIL import Image


def preview_root() -> Path:
    root = Path(tempfile.gettempdir()) / "ae2claude_previews"
    root.mkdir(parents=True, exist_ok=True)
    return root


def prune_previews(*, max_age_hours: int = 24) -> int:
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for path in preview_root().glob("*.png"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _wait_for_complete_file(path: Path, timeout_seconds: float = 30.0) -> int:
    """Wait until AE's asynchronous PNG writer has stopped growing the file."""
    deadline = time.monotonic() + timeout_seconds
    last_size = -1
    stable_samples = 0
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        if size > 0 and size == last_size:
            stable_samples += 1
            if stable_samples >= 3:
                return size
        else:
            stable_samples = 0
            last_size = size
        time.sleep(0.1)
    raise RuntimeError("AE preview PNG did not finish writing before timeout")


def _optimize_preview(path: Path, max_width: int) -> tuple[int, int, int]:
    max_width = max(320, min(max_width, 4096))
    optimized = path.with_name(f"{path.stem}-optimized.png")
    with Image.open(path) as image:
        image.load()
        if image.width > max_width:
            ratio = max_width / image.width
            target = (max_width, max(1, round(image.height * ratio)))
            image.thumbnail(target, Image.Resampling.LANCZOS)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        width, height = image.size
        image.save(optimized, format="PNG", optimize=True, compress_level=6)
    os.replace(optimized, path)
    return width, height, path.stat().st_size


def render_preview(
    ae: AEBridge,
    time_seconds: float | None = None,
    max_width: int = 1600,
) -> dict[str, Any]:
    prune_previews()
    stamp = int(time.time() * 1000)
    output = preview_root() / f"frame-{stamp}.png"
    requested = "null" if time_seconds is None else repr(float(time_seconds))
    output_json = json.dumps(str(output), ensure_ascii=False)
    code = f"""
(function () {{
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {{
        return JSON.stringify({{ok:false,error:"no_active_comp"}});
    }}
    var requested = {requested};
    var t = requested === null ? comp.time : requested;
    if (t < 0 || t > comp.duration) {{
        return JSON.stringify({{ok:false,error:"time_out_of_range",time:t,duration:comp.duration}});
    }}
    var out = new File({output_json});
    try {{
        comp.saveFrameToPng(t, out);
    }} catch (err) {{
        return JSON.stringify({{ok:false,error:String(err),line:err.line || null}});
    }}
    return JSON.stringify({{
        ok:true,path:out.fsName,comp:comp.name,compId:String(comp.id),
        time:t,width:comp.width,height:comp.height
    }});
}})();
"""
    raw = ae.run_jsx(code, timeout=120_000)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid preview response: {raw}") from exc
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "preview_failed"))
    _wait_for_complete_file(output)
    preview_width, preview_height, size_bytes = _optimize_preview(output, max_width)
    result["path"] = str(output)
    result["sizeBytes"] = size_bytes
    result["previewWidth"] = preview_width
    result["previewHeight"] = preview_height
    return result
