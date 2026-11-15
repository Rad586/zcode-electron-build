"""Exercise the pinned trim anchors and ICU resource package independently."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHROMIUM = HERE.parent / 'chromium-152.0.7977.169'
ELECTRON = HERE.parent / 'electron-44.10.2'


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trim = load('apply-runtime-trim')
icu = load('trim-icu')


class TrimTests(unittest.TestCase):
    def test_pinned_patch_is_atomic_on_anchor_failure(self):
        files = ['build/config/locales.gni', 'components/spellcheck/spellcheck_build_features.gni',
                 'content/browser/devtools/features.gni', 'electron/build/electron_paks.gni',
                 'electron/build/args/all.gn',
                 'gpu/command_buffer/service/shared_image/d3d_image_backing_factory.cc',
                 'third_party/blink/renderer/platform/runtime_enabled_features.json5',
                 'electron/shell/app/electron_main_delegate.cc', 'electron/BUILD.gn',
                 'printing/BUILD.gn', 'media/BUILD.gn', 'media/cdm/BUILD.gn',
                 'media/cdm/library_cdm/cdm_paths.gni', 'chrome/browser/ui/BUILD.gn',
                 'chrome/browser/policy/BUILD.gn', 'chrome/browser/BUILD.gn',
                 'chrome/browser/sync/BUILD.gn', 'chrome/browser/guest_view/BUILD.gn']
        files += ['third_party/blink/renderer/modules/' + name for name in trim.IDL_GATES]
        with tempfile.TemporaryDirectory(dir=HERE) as work:
            root = Path(work)
            for name in files:
                source = ELECTRON / name[9:] if name.startswith('electron/') else CHROMIUM / name
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            (root / '.gn').write_text('buildconfig = "//build/config/BUILDCONFIG.gn"\n')
            files.append('.gn')
            devtools = root / 'chrome/browser/devtools/BUILD.gn'
            devtools.parent.mkdir(parents=True, exist_ok=True)
            devtools.write_text('if (enable_devtools_frontend) {\n'
                                '  import("//chrome/common/features.gni")\n'
                                '  import("//tools/grit/grit_rule.gni")\n}\n'
                                'if (enable_service_discovery) {}\n')
            files.append('chrome/browser/devtools/BUILD.gn')
            chrome_test = root / 'chrome/test/BUILD.gn'
            chrome_test.parent.mkdir(parents=True, exist_ok=True)
            chrome_test.write_text('    deps += [\n'
                                   '      "//chrome/browser/ui/webui/print_preview:interactive_ui_tests",\n'
                                   '    ]\n')
            files.append('chrome/test/BUILD.gn')
            trim.patch(root)
            dotfile = (root / '.gn').read_text()
            self.assertIn('root = "//electron:electron_dist_zip"\n', dotfile)
            self.assertIn('root_patterns = [ "//electron:electron_dist_zip" ]\n', dotfile)
            args = (root / 'electron/build/args/all.gn').read_text()
            self.assertNotIn('root_extra_deps =', args)
            self.assertNotIn('enable_linux_installer =', args)
            d3d = (root / 'gpu/command_buffer/service/shared_image/d3d_image_backing_factory.cc').read_text()
            swap_chain = d3d.split('bool D3DImageBackingFactory::IsSwapChainSupported(', 1)[1].split('\n}', 1)[0]
            guarded, direct_composition = swap_chain.split('#endif', 1)
            self.assertIn('#if BUILDFLAG(SKIA_USE_DAWN)', guarded)
            self.assertIn('dawn_context_provider->GetD3D11Device()', guarded)
            self.assertIn('return gl::DirectCompositionSupported() &&', direct_composition)
            self.assertIn('if (enable_spellcheck) {\n'
                          '      deps += [ "//chrome/browser/spellchecker", "//components/spellcheck/browser" ]',
                          (root / 'chrome/browser/ui/BUILD.gn').read_text())
            self.assertIn('if (enable_spellcheck) {\n'
                          '    deps += [ "//chrome/browser/spellchecker", "//components/spellcheck/browser" ]',
                          (root / 'chrome/browser/policy/BUILD.gn').read_text())
            browser = (root / 'chrome/browser/BUILD.gn').read_text()
            self.assertIn('if (enable_spellcheck) {\n'
                          '    deps += [ "//chrome/browser/spellchecker", "//components/spellcheck/browser" ]',
                          browser)
            self.assertIn('"//chrome/browser/spellchecker:impl"', browser)
            sync = (root / 'chrome/browser/sync/BUILD.gn').read_text()
            self.assertIn('if (enable_spellcheck) {\n'
                          '    deps += [ "//components/spellcheck/browser" ]', sync)
            self.assertIn('if (enable_spellcheck) {\n'
                          '    deps += [ "//chrome/browser/spellchecker" ]', sync)
            self.assertIn('assert(enable_library_cdms || is_win)',
                          (root / 'media/cdm/library_cdm/cdm_paths.gni').read_text())
            media = (root / 'media/BUILD.gn').read_text()
            self.assertIn('if (enable_library_cdms || is_win) {\n  import("//media/cdm/library_cdm/cdm_paths.gni")', media)
            self.assertIn('if (enable_library_cdms || is_win) {\n    flags += [', media)
            self.assertIn('if (enable_library_cdms || is_win) {\n  static_library("cdm_paths") {',
                          (root / 'media/cdm/BUILD.gn').read_text())
            self.assertIn('assert(enable_printing || enable_pdf)',
                          (root / 'printing/BUILD.gn').read_text())
            self.assertIn('if (enable_print_preview) {\n      deps += [', chrome_test.read_text())
            guest = (root / 'chrome/browser/guest_view/BUILD.gn').read_text()
            self.assertIn('if (enable_print_preview) {\n'
                          '      deps += [ "//chrome/browser/ui/webui/print_preview" ]', guest)
            self.assertIn('if (enable_printing) {\n'
                          '      deps += [ "//chrome/browser/printing:test_support" ]', guest)
            self.assertTrue(devtools.read_text().startswith(
                'import("//chrome/common/features.gni")\n\nif (enable_devtools_frontend) {'))
            locales = (root / 'build/config/locales.gni').read_text()
            self.assertIn('platform_pak_locales = []\n  platform_pak_locales = [ "en-US", "zh-CN", "zh-TW" ] + pseudolocales', locales)
            self.assertLess(locales.index('if (is_win) {\n  platform_pak_locales = []'),
                            locales.index('locales_without_pseudolocales ='))
            paks = (root / 'electron/build/electron_paks.gni').read_text()
            self.assertNotIn('devtools_resources.pak', paks)
            self.assertIn('pdf_resources.pak', paks)
            self.assertIn('tracing_resources.pak', paks)
            features = (root / 'third_party/blink/renderer/platform/runtime_enabled_features.json5').read_text()
            for _, feature in trim.IDL_GATES.values():
                self.assertIn('name: "' + feature + '"', features)
            before = {name: (root / name).read_bytes() for name in files}
            with self.assertRaises(RuntimeError):
                trim.patch(root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in files})

    def test_spellcheck_dependency_lists(self):
        source = '''source_set("sample") {
  deps = [ "//base", "//chrome/browser/spellchecker" ]
  public_deps += [
    # Keep comment [ "//chrome/browser/spellchecker" ].
    "//components/spellcheck/browser:test_support",
    "//components/spellcheck:buildflags",
  ]
  if (is_win) {
    data_deps = [ "//chrome/browser/spellchecker:impl" ]
  }
}
'''
        result = trim.gate_trimmed_dependencies(source)
        self.assertEqual(result.count(trim.SPELLCHECK_IMPORT), 1)
        self.assertIn('deps = [ "//base", ]', result)
        self.assertIn('if (enable_spellcheck) {\n'
                      '    deps += [ "//chrome/browser/spellchecker" ]', result)
        self.assertIn('public_deps += [ "//components/spellcheck/browser:test_support" ]', result)
        self.assertIn('    if (enable_spellcheck) {\n'
                      '      data_deps += [ "//chrome/browser/spellchecker:impl" ]', result)
        self.assertIn('"//components/spellcheck:buildflags",', result)
        self.assertIn('# Keep comment [ "//chrome/browser/spellchecker" ].', result)
        self.assertEqual(trim.gate_trimmed_dependencies('deps = [ "//base" ]'),
                         'deps = [ "//base" ]')

    def test_print_dependency_lists_preserve_pdf(self):
        source = '''source_set("sample") {
  deps = [
    "//chrome/browser/ui/webui/print_preview:impl",
    "//chrome/browser/printing",
    "//pdf",
    "//printing",
    "//components/pdf/browser",
  ]
}
'''
        result = trim.gate_trimmed_dependencies(source)
        self.assertEqual(result.count('import("//printing/buildflags/buildflags.gni")'), 1)
        self.assertIn('if (enable_print_preview) {\n'
                      '    deps += [ "//chrome/browser/ui/webui/print_preview:impl" ]', result)
        self.assertIn('if (enable_printing) {\n'
                      '    deps += [ "//chrome/browser/printing" ]', result)
        for label in ['//pdf', '//printing', '//components/pdf/browser']:
            self.assertIn('    "' + label + '",', result)

    def test_icu_with_real_v8_intl(self):
        runtime = Path('F:/zcode/diagnostics/runtimes/electron-44.10.2-win32-x64')
        original = (runtime / 'icudtl.dat').read_bytes()
        result = icu.trim(original)
        self.assertEqual(result, icu.trim(result))
        _, old = icu.entries(original)
        _, new = icu.entries(result)
        new = dict(new)
        for name, payload in old:
            relative = name.split('/', 1)[1]
            if not relative.endswith('.res') or relative.startswith('brkitr/'):
                self.assertEqual(new[name], payload)
        self.assertNotIn('icudt78l/fr.res', new)
        self.assertNotIn('icudt78l/lang/de.res', new)
        for name in ['root', 'en', 'zh', 'zh_Hant', 'pool', 'supplementalData',
                     'plurals', 'numberingSystems', 'zoneinfo64', 'metadata', 'icuver', 'icustd']:
            self.assertIn('icudt78l/' + name + '.res', new)
        with tempfile.TemporaryDirectory(dir=HERE) as work:
            root = Path(work)
            (root / 'icudtl.dat').write_bytes(result)
            for name in ['electron.exe', 'ffmpeg.dll', 'snapshot_blob.bin', 'v8_context_snapshot.bin']:
                shutil.copyfile(runtime / name, root / name)
            import os
            env = dict(os.environ, ELECTRON_RUN_AS_NODE='1')
            script = """
const a = require('node:assert/strict');
for (const locale of ['en-US', 'en-GB', 'zh-CN', 'zh-TW', 'zh-HK']) {
  a.equal(Intl.DateTimeFormat.supportedLocalesOf([locale]).length, 1);
  a.equal(Intl.NumberFormat.supportedLocalesOf([locale]).length, 1);
  a.equal(Intl.Collator.supportedLocalesOf([locale]).length, 1);
  a(new Intl.DateTimeFormat(locale, {timeZone:'Asia/Shanghai', dateStyle:'full'}).format(0));
  a(new Intl.NumberFormat(locale, {style:'currency', currency:'CNY'}).format(12345.6));
  a(new Intl.DisplayNames(locale, {type:'region'}).of('TW'));
  a(new Intl.RelativeTimeFormat(locale).format(-2, 'day'));
  a(new Intl.ListFormat(locale).format(['甲','乙']));
  a([...new Intl.Segmenter(locale, {granularity:'word'}).segment('中文测试 hello world')].length > 2);
  a(new Intl.Collator(locale).compare('abc', 'xyz') < 0);
}
a.equal(Intl.DateTimeFormat.supportedLocalesOf(['fr', 'de', 'ja']).length, 0);
for (const zone of ['UTC', 'Asia/Shanghai', 'Asia/Taipei', 'America/New_York', 'Europe/London'])
  a(new Intl.DateTimeFormat('zh-CN', {timeZone:zone}).format(0));
for (const encoding of ['gb18030', 'big5', 'shift_jis', 'windows-1252', 'euc-kr'])
  a(new TextDecoder(encoding).decode(new Uint8Array([65])) === 'A');
a.equal('e\\u0301'.normalize('NFC'), 'é');
a(new Intl.Segmenter('zh-CN').segment('👨‍👩‍👧‍👦')[Symbol.iterator]().next().value.segment.length > 1);
console.log('ICU Intl checks passed');
"""
            subprocess.run([str(root / 'electron.exe'), '-e', script], env=env,
                           check=True, capture_output=True, text=True, timeout=45,
                           creationflags=subprocess.CREATE_NO_WINDOW)


if __name__ == '__main__':
    unittest.main()
