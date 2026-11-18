"""Exercise the pinned trim anchors and ICU resource package independently."""
import importlib.util
from pathlib import Path
import re
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


def without_feature(text, flag):
    guards = []
    for line in text.splitlines():
        if re.match(r'#if(?:def|ndef)?\b', line):
            guards.append(line == '#if BUILDFLAG(' + flag + ')')
        elif line.startswith('#endif'):
            guards.pop()
        elif line.startswith('#else') and guards and guards[-1]:
            guards[-1] = False
        elif not any(guards):
            yield line
    if guards:
        raise AssertionError('Unbalanced preprocessor guards')


class TrimTests(unittest.TestCase):
    def test_pinned_patch_is_atomic_on_anchor_failure(self):
        files = ['build/config/locales.gni', 'components/spellcheck/spellcheck_build_features.gni',
                 'content/browser/devtools/features.gni', 'content/child/runtime_features.cc',
                 'electron/build/electron_paks.gni',
                 'electron/build/args/all.gn', 'electron/chromium_src/BUILD.gn',
                 'electron/buildflags/BUILD.gn',
                 'electron/shell/renderer/api/electron_api_web_frame.cc',
                 'electron/shell/browser/ui/inspectable_web_contents.cc',
                 'electron/shell/browser/ui/devtools_ui_bundle_data_source.cc',
                 'printing/common/metafile_utils.cc',
                 'gpu/command_buffer/service/shared_image/d3d_image_backing_factory.cc',
                 'gpu/ipc/service/gpu_init.cc',
                 'third_party/blink/renderer/platform/runtime_enabled_features.json5',
                 'third_party/blink/common/origin_trials/manual_completion_origin_trial_features.cc',
                 'electron/shell/app/electron_main_delegate.cc', 'electron/BUILD.gn',
                 'printing/BUILD.gn', 'media/BUILD.gn', 'media/cdm/BUILD.gn',
                 'media/cdm/library_cdm/cdm_paths.gni', 'media/cdm/cdm_paths.h',
                 'chrome/browser/ui/BUILD.gn',
                 'chrome/browser/policy/BUILD.gn', 'chrome/browser/BUILD.gn',
                 'chrome/browser/sync/BUILD.gn', 'chrome/browser/guest_view/BUILD.gn']
        d3d_files = ['gpu/command_buffer/service/shared_image/d3d_image_' + name
                     for name in ('backing.cc', 'backing.h', 'representation.cc', 'representation.h')]
        files += d3d_files + ['third_party/blink/renderer/modules/' + name for name in trim.IDL_GATES]
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
            gpu_init = (root / 'gpu/ipc/service/gpu_init.cc').read_text()
            composition = gpu_init.split('gl::SolidColorPoolFactory solid_color_factory;', 1)[1]
            dawn, angle = composition.split('#endif  // BUILDFLAG(SKIA_USE_DAWN)', 1)
            self.assertTrue(dawn.startswith('\n#if BUILDFLAG(SKIA_USE_DAWN)\n'))
            self.assertIn('dawn_context_provider_->GetD3D11Device()', dawn)
            self.assertIn('dawn_context_provider_->GetD3D12CommandQueue()', dawn)
            self.assertTrue(angle.startswith('\n    {\n      d3d11_device = gl::QueryD3D11DeviceObjectFromANGLE();'))
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
            electron_spellcheck = (root / 'electron/chromium_src/BUILD.gn').read_text().split(
                'source_set("chrome_spellchecker") {', 1)[1]
            self.assertIn('if (enable_spellcheck) {\n'
                          '    public_deps += [ "//components/spellcheck/browser", '
                          '"//components/spellcheck/renderer" ]', electron_spellcheck)
            self.assertIn('    "//components/spellcheck/common",', electron_spellcheck)
            electron_build = (root / 'electron/BUILD.gn').read_text()
            self.assertIn('if (!enable_builtin_spellchecker) {\n    sources -= [\n'
                          '      "shell/renderer/api/electron_api_spell_check_client.cc",', electron_build)
            web_frame = '\n'.join(without_feature(
                (root / 'electron/shell/renderer/api/electron_api_web_frame.cc').read_text(),
                'ENABLE_BUILTIN_SPELLCHECKER'))
            self.assertNotRegex(web_frame, r'SpellCheckClient|FrameSetSpellChecker|'
                                r'SpellCheckerHolder|setSpellCheckProvider|components/spellcheck/renderer/')
            self.assertIn('.SetMethod("insertText",', web_frame)
            buildflags = (root / 'electron/buildflags/BUILD.gn').read_text()
            self.assertIn('"ENABLE_DEVTOOLS_FRONTEND=$enable_devtools_frontend",', buildflags)
            inspectable = '\n'.join(without_feature(
                (root / 'electron/shell/browser/ui/inspectable_web_contents.cc').read_text(),
                'ENABLE_DEVTOOLS_FRONTEND'))
            self.assertNotIn('DevToolsFrontendHost::Create(', inspectable)
            self.assertNotIn('GetDevToolsURL(', inspectable)
            self.assertNotIn('DevToolsEmbedderMessageDispatcher::CreateForDevToolsFrontend(', inspectable)
            self.assertIn('agent_host_->AttachClient(this);', inspectable)
            self.assertIn('void InspectableWebContents::DispatchProtocolMessage(', inspectable)
            bundle = '\n'.join(without_feature(
                (root / 'electron/shell/browser/ui/devtools_ui_bundle_data_source.cc').read_text(),
                'ENABLE_DEVTOOLS_FRONTEND'))
            self.assertNotIn('DevToolsFrontendHost::GetFrontendResourceBytes(', bundle)
            self.assertNotIn('PathWithoutParams(', bundle)
            self.assertIn('std::move(callback).Run(bytes);', bundle)
            metafile = '\n'.join(without_feature(
                (root / 'printing/common/metafile_utils.cc').read_text(), 'ENABLE_PRINTING'))
            self.assertNotIn('SkPDF::', metafile)
            self.assertIn('  return nullptr;', metafile)
            for name in ('GetEmptyPicture', 'SerializeOopPicture', 'DeserializeOopPicture',
                         'SerializeRasterImage', 'DeserializeRasterImage', 'SerializationProcs'):
                self.assertIn(name + '(', metafile)
            self.assertIn('assert(enable_library_cdms || is_win)',
                          (root / 'media/cdm/library_cdm/cdm_paths.gni').read_text())
            media = (root / 'media/BUILD.gn').read_text()
            self.assertIn('if (enable_library_cdms || is_win) {\n  import("//media/cdm/library_cdm/cdm_paths.gni")', media)
            self.assertIn('if (enable_library_cdms || is_win) {\n    flags += [', media)
            self.assertIn('if (enable_library_cdms || is_win) {\n  static_library("cdm_paths") {',
                          (root / 'media/cdm/BUILD.gn').read_text())
            self.assertIn('#if !BUILDFLAG(ENABLE_LIBRARY_CDMS) && !BUILDFLAG(IS_WIN)',
                          (root / 'media/cdm/cdm_paths.h').read_text())
            printing = (root / 'printing/BUILD.gn').read_text()
            self.assertIn('assert(enable_printing || enable_pdf)', printing)
            self.assertIn('if (!enable_basic_print_dialog && !is_win) {\n'
                          '    sources += [\n'
                          '      "printing_context_no_system_dialog.cc",', printing)
            windows = printing.split('component("printing") {', 1)[1].split('  if (is_win) {', 1)[1].split('\n  }', 1)[0]
            self.assertIn('"printing_context_system_dialog_win.cc",', windows)
            self.assertIn('"printing_context_win.cc",', windows)
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
            trim_at = locales.index('if (is_win) {\n  platform_pak_locales = []')
            self.assertLess(locales.index('locales_without_pseudolocales ='), trim_at)
            self.assertLess(locales.index('locales_with_pseudolocales ='), trim_at)
            self.assertLess(trim_at, locales.index('if (!enable_pseudolocales) {'))
            paks = (root / 'electron/build/electron_paks.gni').read_text()
            self.assertNotIn('devtools_resources.pak', paks)
            self.assertIn('pdf_resources.pak', paks)
            self.assertIn('tracing_resources.pak', paks)
            features = (root / 'third_party/blink/renderer/platform/runtime_enabled_features.json5').read_text()
            manual_trials = (root / 'third_party/blink/common/origin_trials/manual_completion_origin_trial_features.cc').read_text()
            self.assertNotIn('OriginTrialFeature::kXSLT', manual_trials)
            self.assertIn('OriginTrialFeature::kRTCEncodedFrameSetMetadata', manual_trials)
            runtime_features = (root / 'content/child/runtime_features.cc').read_text()
            self.assertNotRegex(runtime_features, r'\{wf::Enable(?:' + '|'.join(trim.BLINK_FEATURES) + r'),')
            self.assertNotIn('blink::features::kXSLT', runtime_features)
            self.assertIn('{wf::EnableWebXRSpecParity,\n'
                          '           raw_ref(device::features::kWebXRIncubations)},\n'
                          '#endif\n'
                          '      };\n'
                          '  for (const auto& mapping : blinkFeatureToBaseFeatureMapping)',
                          runtime_features)
            self.assertIn('WebRuntimeFeatures::EnableXSLT(value == "true");', runtime_features)
            d3d_without_dawn = '\n'.join(line for name in d3d_files
                                         for line in without_feature((root / name).read_text(), 'SKIA_USE_DAWN'))
            d3d_without_dawn = re.sub(r'//[^\n]*', '', d3d_without_dawn)
            self.assertNotRegex(d3d_without_dawn,
                                r'dawn::|DawnContextProvider|DawnSharedTextureCache|'
                                r'PersistentGraphiteDawnAccess|DawnD3D\w+Representation|'
                                r'GraphiteDawnImageRepresentation|FlushGraphiteCommandsIfNeeded|'
                                r'NotifyGraphiteAboutInitializedStatus|\bProduceDawn(?:Buffer)?\b')
            for name in ('BeginAccessD3D11', 'BeginAccessD3D12', 'EndAccessD3D',
                         'GetPendingWaitFences', 'EnsureD3D12Resource', 'PresentSwapChain',
                         'ProduceOverlay', 'ProduceVideo', 'CopyToStagingTexture'):
                self.assertIn('D3DImageBacking::' + name + '(', d3d_without_dawn)
            self.assertIn('auto unwrapped_d3d12_resource = EnsureD3D12Resource();', d3d_without_dawn)
            self.assertIn('wait_fences.push_back(std::move(dcomp_texture_available_fence_));',
                          d3d_without_dawn)
            for feature in trim.BLINK_FEATURES:
                block = re.search(r'name: "' + re.escape(feature) + r'",(.*?)\n    \},', features, re.S)
                self.assertIsNotNone(block, feature)
                self.assertNotIn('origin_trial_', block[1], feature)
                self.assertIn('base_feature: "none"', block[1], feature)
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
