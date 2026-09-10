from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from ae2claude_mcp import frame_review as review


class FrameReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {"AE2CLAUDE_PREVIEW_ROOT": str(self.root),
                                     "AE2CLAUDE_KILL_SWITCH_FILE": str(self.root / "disabled")})
        env.start()
        self.addCleanup(env.stop)

    def frame(self, image, t=0, comp="1"):
        path = self.root / f"frame-{len(list(self.root.glob('*.png')))}.png"
        image.save(path)
        return {"path": str(path), "time": t, "compId": comp,
                "width": image.width, "height": image.height,
                "previewWidth": image.width, "previewHeight": image.height,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def capture(self, frames):
        with patch.object(review, "render_preview", side_effect=frames):
            return review.capture_frames(Mock(), times=[f["time"] for f in frames])

    def test_range_validation(self):
        self.assertEqual(review.review_times(None, 0, 1, 3), [0, .5, 1])
        for args in [([], None, None, 6), ([float('nan')], None, None, 6),
                     ([0], 0, 1, 6), (None, 0, 1, 17), ([-1], None, None, 6)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                review.review_times(*args)

    def test_grid_geometry_labels_and_persistent_capture(self):
        frames = [self.frame(Image.new('RGB', (160, 90), color), i)
                  for i, color in enumerate(['red', 'green', 'blue'])]
        result = self.capture(frames)
        with Image.open(result['grid']['path']) as grid:
            self.assertLessEqual(max(grid.size), 1600)
            for cell, color in zip(result['grid']['cells'], [(255, 0, 0), (0, 128, 0), (0, 0, 255)]):
                self.assertEqual(grid.getpixel((cell['x'] + 40, cell['y'] + 30)), color)
        self.assertEqual(review.stored_frame(result['captureId'], 2)['time'], 2)

    def test_known_pixel_difference_threshold_and_bbox(self):
        left = Image.new('RGB', (10, 10), 'black')
        right = left.copy()
        right.putpixel((3, 4), (20, 0, 0))
        result = self.capture([self.frame(left), self.frame(right, 1)])
        cid = result['captureId']
        diff = review.compare_frames(cid, 0, cid, 1, 8)
        self.assertEqual(diff['changedPixels'], 1)
        self.assertEqual(diff['changedRatio'], .01)
        self.assertEqual(diff['bbox'], (3, 4, 4, 5))
        self.assertEqual(diff['maxAbsDiff'], 20)
        self.assertEqual(review.compare_frames(cid, 0, cid, 1, 20)['changedPixels'], 0)
        same = review.compare_frames(cid, 0, cid, 0)
        self.assertEqual(same['changedRatio'], 0)
        self.assertIsNone(same['bbox'])

    def test_alpha_and_hidden_rgb(self):
        a = Image.new('RGBA', (10, 10), (255, 0, 0, 0))
        b = Image.new('RGBA', (10, 10), (0, 0, 255, 0))
        result = self.capture([self.frame(a), self.frame(b, 1)])
        cid = result['captureId']
        self.assertEqual(review.compare_frames(cid, 0, cid, 1)['changedPixels'], 0)
        b.putpixel((0, 0), (0, 0, 0, 255))
        other = self.capture([self.frame(b)])
        self.assertEqual(review.compare_frames(cid, 0, other['captureId'], 0)['changedPixels'], 1)

    def test_tampering_dimensions_and_traversal_rejected(self):
        result = self.capture([self.frame(Image.new('RGB', (10, 10)))])
        cid = result['captureId']
        other = self.capture([self.frame(Image.new('RGB', (20, 10)))])
        with self.assertRaises(ValueError):
            review.compare_frames(cid, 0, other['captureId'], 0)
        Path(result['frames'][0]['path']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            review.stored_frame(cid, 0)
        with self.assertRaises(ValueError):
            review.stored_frame('../escape', 0)

    def test_comp_switch_and_kill_switch_abort(self):
        frames = [self.frame(Image.new('RGB', (10, 10)), comp=c) for c in ['1', '2']]
        with self.assertRaises(RuntimeError):
            self.capture(frames)
        (self.root / 'disabled').touch()
        with self.assertRaises(PermissionError):
            self.capture(frames[:1])

    def test_inline_is_bounded_and_original_unchanged(self):
        image = Image.effect_noise((1000, 1000), 100).convert('RGB')
        frame = self.frame(image)
        data = review.inline_png(frame['path'], max_bytes=200_000)
        self.assertLessEqual(len(data), 200_000)
        self.assertEqual(hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest(), frame['sha256'])
