"""Check pinned patch anchors and metadata-driven currentColor generation."""
import importlib.util
from pathlib import Path
import os
import shutil
from types import SimpleNamespace
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined
import json5

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('ZCODE_CURRENTCOLOR_SOURCE',
                             HERE.parent / 'chromium-152.0.7977.169'))
spec = importlib.util.spec_from_file_location('currentcolor', HERE / 'apply-currentcolor.py')
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class Name:
    def __init__(self, text):
        self.text = text

    def to_upper_camel_case(self):
        return ''.join(part.capitalize() for part in self.text.split('-'))


class PatchTests(unittest.TestCase):
    def test_pinned_sources_and_atomic_failure(self):
        with tempfile.TemporaryDirectory(dir=HERE) as work:
            root = Path(work)
            for name in patcher.EDITS:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SOURCE / name, target)
            original = {name: (root / name).read_bytes() for name in patcher.EDITS}
            # Fail on the final file after the first file has been prepared.
            style = root / patcher.STYLE
            style.write_text('mismatched source', encoding='utf-8')
            before = {name: (root / name).read_bytes() for name in patcher.EDITS}
            with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
                patcher.patch(root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in patcher.EDITS})
            style.write_bytes(original[patcher.STYLE])
            patcher.patch(root)
            generated = (root / patcher.TEMPLATE).read_text(encoding='utf-8')
            self.assertIn(patcher.DISPATCH, generated)
            self.assertNotIn('bool ComputedStyle::HasPropertyDependingOnCurrentColor()',
                             style.read_text(encoding='utf-8'))
            before = {name: (root / name).read_bytes() for name in patcher.EDITS}
            with self.assertRaisesRegex(RuntimeError, 'patch anchor'):
                patcher.patch(root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in patcher.EDITS})

    def test_all_pinned_properties_once_in_source_order_without_aliases(self):
        metadata = json5.loads((SOURCE / 'third_party/blink/renderer/core/css/css_properties.json5')
                               .read_text(encoding='utf-8'))
        properties = [SimpleNamespace(name=Name(prop['name']),
                                     includes_currentcolor=prop.get('includes_currentcolor', False),
                                     alias_for=prop.get('alias_for')) for prop in metadata['data']]
        expected = [prop.name.to_upper_camel_case() for prop in properties
                    if prop.includes_currentcolor and not prop.alias_for]
        self.assertEqual(len(expected), 29)
        # Future unrelated properties and aliases must not add dispatches.
        properties += [SimpleNamespace(name=Name('unrelated'), includes_currentcolor=False,
                                       alias_for=None),
                       SimpleNamespace(name=Name('alias'), includes_currentcolor=True,
                                       alias_for='background-color')]
        template = Environment(undefined=StrictUndefined).from_string(patcher.DISPATCH)
        rendered = template.render(properties=properties, is_longhand=True)
        calls = [line.strip() for line in rendered.splitlines() if 'if (' in line]
        self.assertEqual(calls, [f'if (static_cast<const css_longhand::{name}&>(GetCSSProperty{name}())'
                                 for name in expected])
        direct_calls = [line.strip() for line in rendered.splitlines()
                        if '::IsAffectedByCurrentColor(' in line]
        self.assertEqual(direct_calls, [f'.css_longhand::{name}::IsAffectedByCurrentColor(*this)) {{'
                                        for name in expected])
        self.assertEqual(template.render(properties=properties, is_longhand=False).strip(), '')
        self.assertEqual(rendered.count('return true;'), len(expected))
        self.assertEqual(rendered.count('return false;'), 1)


if __name__ == '__main__':
    unittest.main()
