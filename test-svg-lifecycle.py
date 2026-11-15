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
        with tempfile.TemporaryDirectory(dir=HERE) as work:
            root = Path(work)
            for name in svg_patch.EDITS:
                source = SOURCE / svg_patch.DIRECTORY / name
                target = root / svg_patch.DIRECTORY / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
            svg_patch.patch(root)
            for name, edits in svg_patch.EDITS.items():
                text = (root / svg_patch.DIRECTORY / name).read_text(encoding='utf-8')
                for _, replacement in edits:
                    self.assertIn(replacement, text)
            before = {name: (root / svg_patch.DIRECTORY / name).read_bytes()
                      for name in svg_patch.EDITS}
            with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
                svg_patch.patch(root)
            self.assertEqual(before, {name: (root / svg_patch.DIRECTORY / name).read_bytes()
                                      for name in svg_patch.EDITS})


if __name__ == '__main__':
    unittest.main()
