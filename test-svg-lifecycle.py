"""Check patch anchors against pinned Chromium sources without modifying them."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('svg_patch', HERE / 'apply-svg-lifecycle.py')
svg_patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(svg_patch)
SOURCE = HERE.parent / 'chromium-152.0.7977.169'


class PatchTests(unittest.TestCase):
    def test_pinned_sources_and_atomic_anchor_failure(self):
        for cache in (False, True):
            with self.subTest(cache=cache), tempfile.TemporaryDirectory(dir=HERE) as work:
                self.check_patch(Path(work), cache)

    def check_patch(self, root, cache):
        edits = svg_patch.EDITS
        cache_edits = svg_patch.CACHE_EDITS
        files = edits.keys() | cache_edits.keys()
        for name in files:
            source = SOURCE / svg_patch.DIRECTORY / name
            target = root / svg_patch.DIRECTORY / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        svg_patch.patch(root, paint_record_cache=cache)
        for name in files:
            text = (root / svg_patch.DIRECTORY / name).read_text(encoding='utf-8')
            for _, replacement in (cache_edits if cache and name in cache_edits else edits).get(name, ()):
                self.assertIn(replacement, text)
        image = (root / svg_patch.DIRECTORY / 'svg_image.cc').read_text(encoding='utf-8')
        self.assertEqual('cached_paint_record_' in image, cache)
        before = {name: (root / svg_patch.DIRECTORY / name).read_bytes() for name in files}
        with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
            svg_patch.patch(root, paint_record_cache=cache)
        self.assertEqual(before, {name: (root / svg_patch.DIRECTORY / name).read_bytes() for name in files})


if __name__ == '__main__':
    unittest.main()
