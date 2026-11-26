"""Check the lazy flex measurement patch against the pinned source."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('flex_layout_space', HERE / 'apply-flex-layout-space.py')
flex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flex)
SOURCE = HERE.parent / 'chromium-152.0.7977.169' / flex.SOURCE


class PatchTests(unittest.TestCase):
    def test_replaces_only_the_five_consumers(self):
        original = SOURCE.read_text(encoding='utf-8')
        patched = flex.render(original)
        self.assertEqual(patched.count('MeasureSpace()'), 5)
        self.assertEqual(patched.count('measure_space.emplace('), 1)
        restored = patched.replace(flex.LAZY, flex.EAGER)
        for old, new in flex.CALLS:
            restored = restored.replace(new, old)
        self.assertEqual(restored, original)

    def test_rejects_unexpected_anchor_or_repeat_without_writing(self):
        original = SOURCE.read_text(encoding='utf-8')
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            root = Path(directory)
            target = root / flex.SOURCE
            target.parent.mkdir(parents=True)
            cases = {
                'new consumer': original.replace(flex.EAGER, flex.EAGER + '\n    Use(child_space);'),
                'changed declaration': original.replace(flex.EAGER, flex.EAGER.replace('const auto', 'const ConstraintSpace')),
                'changed call': original.replace(flex.CALLS[-1][0], 'table_child->Other(child_space)'),
                'already patched': flex.render(original),
            }
            for case, text in cases.items():
                with self.subTest(case=case):
                    target.write_bytes(text.encode('utf-8'))
                    with self.assertRaises(RuntimeError):
                        flex.patch(root)
                    self.assertEqual(target.read_bytes(), text.encode('utf-8'))
            target.write_bytes(original.encode('utf-8'))
            flex.patch(root)
            self.assertEqual(target.read_text(encoding='utf-8'), flex.render(original))


if __name__ == '__main__':
    unittest.main()
