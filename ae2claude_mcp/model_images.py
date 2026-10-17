"""Bounded visual previews, separate from source and pixel-comparison artifacts."""
from __future__ import annotations

import hashlib
import io
import json
import uuid
from pathlib import Path
from typing import Any

MAX_SIDE = 1600
MAX_BYTES = 750_000  # Encoded bytes; base64 is at most 1 MB per image.


def prepare_image(path: str, crop: list[int] | None = None) -> dict[str, Any]:
    """Create an 8-bit WebP overview or source-pixel crop without changing source."""
    from PIL import Image, ImageOps
    from .previews import preview_root, prune_previews

    source = Path(path).expanduser().resolve(strict=True)
    with Image.open(source) as opened:
        if getattr(opened, "n_frames", 1) != 1:
            raise ValueError("Use a single still frame; animated/multipage images are not accepted")
        oriented = ImageOps.exif_transpose(opened)
        width, height = oriented.size
        box = [0, 0, width, height] if crop is None else crop
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(type(v) is not int for v in box)
                or not 0 <= box[0] < box[2] <= width
                or not 0 <= box[1] < box[3] <= height):
            raise ValueError("crop must be [left, top, right, bottom] within oriented source pixels")
        has_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
        image = oriented.crop(box).convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    # Keep a readable quality floor; reduce dimensions only when the budget demands it.
    while True:
        for quality in (88, 82, 78):
            buffer = io.BytesIO()
            image.save(buffer, format="WEBP", quality=quality, method=4, exact=True)
            data = buffer.getvalue()
            if len(data) <= MAX_BYTES:
                break
        else:
            if max(image.size) <= 640:
                raise ValueError("Image exceeds preview budget; request a smaller source crop")
            side = max(640, int(max(image.size) * .8))
            image.thumbnail((side, side), Image.Resampling.LANCZOS)
            continue
        break
    prune_previews()
    output = preview_root() / f"model-{uuid.uuid4().hex}.webp"
    output.write_bytes(data)
    return {
        "path": str(output), "mimeType": "image/webp", "sizeBytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "width": image.width,
        "height": image.height, "quality": quality, "hasAlpha": has_alpha,
        "sourcePath": str(source), "sourceWidth": width, "sourceHeight": height,
        "crop": list(box), "sourcePixelsPerPreviewPixel": [
            (box[2] - box[0]) / image.width, (box[3] - box[1]) / image.height],
        "purpose": "visual review only; use source pixels for measurements",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--crop", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    args = parser.parse_args()
    print(json.dumps(prepare_image(args.path, args.crop), ensure_ascii=False))


if __name__ == "__main__":
    main()
