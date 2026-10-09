from __future__ import annotations

import base64
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from ae2claude_mcp.model_images import MAX_BYTES, prepare_image
from ae2claude_mcp.previews import prune_previews


class ModelImageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = patch.dict(os.environ, {"AE2CLAUDE_PREVIEW_ROOT": str(self.root / "cache"),
                                     "AE2CLAUDE_KILL_SWITCH_FILE": str(self.root / "disabled")})
        env.start()
        self.addCleanup(env.stop)

    def source(self, image):
        path = self.root / "source.png"
        image.save(path)
        return path

    def test_alpha_crop_mapping_and_original_unchanged(self):
        image = Image.new("RGBA", (2000, 2400), (30, 90, 120, 127))
        image.putpixel((50, 90), (80, 120, 180, 0))
        source = self.source(image)
        before = source.read_bytes()
        result = prepare_image(str(source), [20, 40, 220, 340])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(result["sourcePixelsPerPreviewPixel"], [1, 1])
        self.assertEqual(result["crop"], [20, 40, 220, 340])
        with Image.open(result["path"]) as preview:
            self.assertEqual(preview.getchannel("A").tobytes(), image.crop(result["crop"]).getchannel("A").tobytes())
            self.assertEqual(preview.size, (200, 300))
        overview = prepare_image(str(source))
        self.assertEqual(overview["height"], 1600)

    def test_noise_obeys_budget_and_dimension_floor(self):
        source = self.source(Image.frombytes("RGBA", (1800, 1800), os.urandom(1800 * 1800 * 4)))
        result = prepare_image(str(source))
        self.assertLessEqual(result["sizeBytes"], MAX_BYTES)
        self.assertGreaterEqual(max(result["width"], result["height"]), 640)
        self.assertGreaterEqual(result["quality"], 78)
        self.assertEqual(result["sizeBytes"], Path(result["path"]).stat().st_size)

    def test_reject_bad_crop_without_writing(self):
        source = self.source(Image.new("RGB", (20, 30)))
        for crop in ([], [1, 2, 3], [0, 0, 21, 20], [-1, 0, 5, 5],
                     [0, 0, 0, 5], [False, 0, 5, 5], [0, 0, 4.5, 5]):
            with self.subTest(crop=crop), self.assertRaises(ValueError):
                prepare_image(str(source), crop)
        self.assertFalse((self.root / "cache").exists())

    def test_palette_transparency(self):
        image = Image.new("P", (20, 30))
        image.info["transparency"] = 0
        result = prepare_image(str(self.source(image)))
        with Image.open(result["path"]) as preview:
            self.assertEqual(preview.getchannel("A").getextrema(), (0, 0))

    def test_mcp_images_match_metadata_and_pngs_unchanged(self):
        from ae2claude_mcp import server
        source = self.source(Image.new("RGB", (80, 100), "red"))
        original = source.read_bytes()
        metadata = {"path": str(source), "sha256": hashlib.sha256(original).hexdigest(), "changedPixels": 3}
        with patch.object(server, "bridge"), patch.object(server, "render_preview", return_value=metadata):
            result = server.ae_preview_frame()
        results = [result, server._review_result(metadata, [str(source), str(source)]),
                   server.ae_prepare_image(str(source), [0, 0, 20, 30])]
        for result in results:
            images = [c for c in result.content if c.type == "image"]
            self.assertEqual(len(images), len(result.structuredContent["modelPreviews"]))
            for inline, info in zip(images, result.structuredContent["modelPreviews"]):
                data = base64.b64decode(inline.data, validate=True)
                self.assertEqual(inline.mimeType, "image/webp")
                self.assertLessEqual(len(data), MAX_BYTES)
                self.assertEqual(hashlib.sha256(data).hexdigest(), info["sha256"])
                with Image.open(io.BytesIO(data)) as decoded:
                    self.assertEqual(decoded.format, "WEBP")
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(results[1].structuredContent["changedPixels"], 3)

    def test_prune_only_owned_webp(self):
        cache = self.root / "cache"
        cache.mkdir()
        owned, other = cache / "model-old.webp", cache / "user.webp"
        for file in (owned, other):
            file.write_bytes(b"x")
            os.utime(file, (time.time() - 90000,) * 2)
        self.assertEqual(prune_previews(), 1)
        self.assertTrue(other.exists())

    def test_lazy_module_import(self):
        subprocess.run([sys.executable, "-c", "import sys; import ae2claude_mcp.model_images; assert 'PIL' not in sys.modules"], check=True)


if __name__ == "__main__":
    unittest.main()
