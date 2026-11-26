"""Verify scale invalidation anchors and composition with the SVG cache patch."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'chromium-152.0.7977.169'


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'apply-{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PatchTests(unittest.TestCase):
    def copy_sources(self, *patches, cache=False):
        temporary = tempfile.TemporaryDirectory(dir=HERE)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        files = {Path(patch.DIRECTORY) / name for patch in patches
                 for name in patch.EDITS}
        if cache:
            lifecycle = patches[0]
            files.update(Path(lifecycle.DIRECTORY) / name for name in lifecycle.CACHE_EDITS)
        for name in files:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((SOURCE / name).read_bytes())
        return root, files

    def test_standalone(self):
        scale = load('svg-scale-invalidation')
        root, _ = self.copy_sources(scale)
        scale.patch(root)
        for name, edits in scale.EDITS.items():
            output = (root / scale.DIRECTORY / name).read_text(encoding='utf-8')
            for _, replacement in edits:
                self.assertIn(replacement, output)
        test = root / scale.DIRECTORY / scale.TEST_FILE
        self.assertNotIn(scale.CACHE_TEST, test.read_text(encoding='utf-8'))

    def test_static_lifecycle_composition_and_atomic_failure(self):
        lifecycle, scale = map(load, ('svg-lifecycle', 'svg-scale-invalidation'))
        root, files = self.copy_sources(lifecycle, scale)
        lifecycle.patch(root, paint_record_cache=False)
        test = root / scale.DIRECTORY / scale.TEST_FILE
        original = test.read_text(encoding='utf-8')
        anchor, replacement = scale.EDITS[scale.TEST_FILE][-1]
        test.write_text(original.replace(anchor, ''), encoding='utf-8')
        before = {name: (root / name).read_bytes() for name in files}
        with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
            scale.patch(root)
        self.assertEqual({name: (root / name).read_bytes() for name in files}, before)
        test.write_text(original, encoding='utf-8')
        scale.patch(root)
        patched = test.read_text(encoding='utf-8')
        self.assertIn(replacement, patched)
        self.assertIn(lifecycle.TESTS, patched)
        self.assertNotIn(scale.CACHE_TEST, patched)

    def test_cache_experiment_is_excluded(self):
        lifecycle, scale = map(load, ('svg-lifecycle', 'svg-scale-invalidation'))
        root, files = self.copy_sources(lifecycle, scale, cache=True)
        lifecycle.patch(root)
        before = {name: (root / name).read_bytes() for name in files}
        with self.assertRaisesRegex(RuntimeError, 'static-only lifecycle patch'):
            scale.patch(root)
        self.assertEqual({name: (root / name).read_bytes() for name in files}, before)


if __name__ == '__main__':
    unittest.main()
