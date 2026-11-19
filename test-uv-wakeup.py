"""Check pinned wakeup patch anchors and atomic rejection."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wakeup', HERE / 'apply-uv-wakeup.py')
wakeup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wakeup)


class PatchTests(unittest.TestCase):
    def test_pinned_source_and_atomic_anchor_failure(self):
        source = HERE.parent / 'electron-44.10.2' / wakeup.FILE
        with tempfile.TemporaryDirectory(dir=HERE) as work:
            root = Path(work)
            target = root / wakeup.FILE
            target.parent.mkdir(parents=True)
            target.write_text(source.read_text(encoding='utf-8'), encoding='utf-8')
            wakeup.patch(root)
            self.assertIn(wakeup.NEW, target.read_text(encoding='utf-8'))
            patched = target.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
                wakeup.patch(root)
            self.assertEqual(target.read_bytes(), patched)


if __name__ == '__main__':
    unittest.main()
