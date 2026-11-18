"""Apply the Windows D3D11 runtime profile before GN generation."""
import argparse
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
LOCALES = ('en-US', 'zh-CN', 'zh-TW')
IDL_GATES = {
    'gamepad/navigator_gamepad.idl': ('ImplementedAs=NavigatorGamepad', 'ZCodeGamepad'),
    'service_worker/navigator_service_worker.idl': ('ImplementedAs=NavigatorServiceWorker', 'ZCodeServiceWorker'),
    'encryptedmedia/navigator_request_media_key_system_access.idl': ('ImplementedAs=NavigatorRequestMediaKeySystemAccess', 'ZCodeEncryptedMedia'),
    'mediarecorder/media_recorder.idl': ('ActiveScriptWrappable,', 'ZCodeMediaRecorder'),
    'peerconnection/rtc_peer_connection.idl': ('ActiveScriptWrappable,', 'ZCodePeerConnection'),
    'mediastream/navigator_user_media.idl': ('ImplementedAs=MediaDevices', 'ZCodeMediaCapture'),
    'mediastream/media_devices.idl': ('ActiveScriptWrappable,', 'ZCodeMediaCapture'),
    'mediastream/navigator_media_stream.idl': ('ImplementedAs=NavigatorMediaStream', 'ZCodeMediaCapture'),
}
BLINK_FEATURES = (
    'GetDisplayMedia', 'ScriptedSpeechRecognition', 'ScriptedSpeechSynthesis',
    'UnprefixedSpeechRecognition', 'WebBluetooth', 'WebBluetoothGetDevices',
    'WebBluetoothScanning', 'WebBluetoothWatchAdvertisements', 'WebUSB',
    'WebHID', 'Serial', 'WebXR', 'PushMessaging', 'PaymentRequest',
    'PaymentApp', 'SecurePaymentConfirmation', 'XSLT',
)


SPELLCHECK_IMPORT = 'import("//components/spellcheck/spellcheck_build_features.gni")'
DEPENDENCY_LIST = re.compile(
    r'(?m)^(?P<indent> *)(?P<kind>deps|public_deps|data_deps)\s*\+?=\s*'
    r'\[(?P<body>(?:"(?:\\.|[^"\\])*"|#[^\n]*|[^"#\[\]])*)\]')
GN_LABEL = re.compile(r'#[^\n]*|"(?:\\.|[^"\\])*"[ \t]*,?')
DEPENDENCY_FEATURES = (
    ('enable_spellcheck', SPELLCHECK_IMPORT, re.compile(
        r'"//(?:chrome/browser/spellchecker|components/spellcheck/(?:browser|renderer))(?::[^"\n]+)?"[ \t]*,?')),
    ('enable_printing', 'import("//printing/buildflags/buildflags.gni")', re.compile(
        r'"//chrome/browser/printing(?::[^"\n]+)?"[ \t]*,?')),
    ('enable_print_preview', 'import("//printing/buildflags/buildflags.gni")', re.compile(
        r'"//chrome/browser/ui/webui/print_preview(?::[^"\n]+)?"[ \t]*,?')),
)


def gate_feature_dependencies(text, feature, feature_import, label_pattern):
    def gate(match):
        body = match['body']
        labels = []

        def remove_label(token):
            if not label_pattern.fullmatch(token[0]):
                return token[0]
            labels.append(token[0])
            return ''

        body = GN_LABEL.sub(remove_label, body)
        if not labels:
            return match[0]
        indent = match['indent']
        labels = ', '.join(label.rstrip().rstrip(',') for label in labels)
        original = match[0]
        start, end = match.span('body')
        original = original[:start - match.start()] + body + original[end - match.start():]
        return (original + '\n' + indent + 'if (' + feature + ') {\n' + indent +
                '  ' + match['kind'] + ' += [ ' + labels + ' ]\n' + indent + '}')

    result = DEPENDENCY_LIST.sub(gate, text)
    if result != text and feature_import not in result:
        result = feature_import + '\n' + result
    return result


def gate_trimmed_dependencies(text):
    for feature, feature_import, label_pattern in DEPENDENCY_FEATURES:
        text = gate_feature_dependencies(text, feature, feature_import, label_pattern)
    return text


def patch(root):
    root = Path(root)
    edits = {}

    def replace(name, old, new):
        file = root / name
        text = edits.get(file, file.read_text(encoding='utf-8'))
        if text.count(old) != 1:
            raise RuntimeError(f'{name}: expected one patch anchor: {old[:70]}')
        edits[file] = text.replace(old, new)

    def guard_region(name, first, until, flag):
        file = root / name
        text = edits.get(file, file.read_text(encoding='utf-8'))
        start = text.index(first)
        end = text.index(until, start + len(first))
        replace(name, text[start:end], '#if BUILDFLAG(' + flag + ')\n' +
                text[start:end].rstrip('\n') + '\n#endif  // BUILDFLAG(' + flag + ')\n\n')

    def guard_dawn(name, first, until):
        guard_region(name, first, until, 'SKIA_USE_DAWN')

    file = root / '.gn'
    text = file.read_text(encoding='utf-8')
    if re.search(r'(?m)^\s*(?:root|root_patterns)\s*=', text):
        raise RuntimeError('GN root scope is already configured')
    edits[file] = text + '\nroot = "//electron:electron_dist_zip"\n' + \
        'root_patterns = [ "//electron:electron_dist_zip" ]\n'

    replace('electron/build/args/all.gn',
            'root_extra_deps = [ "//electron" ]\n', '')
    replace('electron/build/args/all.gn', 'enable_linux_installer = false\n', '')

    replace('build/config/locales.gni',
            'if (!enable_pseudolocales) {',
            'if (is_win) {\n'
            '  platform_pak_locales = []\n'
            '  platform_pak_locales = [ "en-US", "zh-CN", "zh-TW" ] + pseudolocales\n'
            '}\n\nif (!enable_pseudolocales) {')
    replace('components/spellcheck/spellcheck_build_features.gni',
            'enable_spellcheck = use_blink', 'enable_spellcheck = false')
    replace('electron/BUILD.gn',
            '  sources = filenames.lib_sources\n',
            '  sources = filenames.lib_sources\n'
            '  if (!enable_builtin_spellchecker) {\n'
            '    sources -= [\n'
            '      "shell/renderer/api/electron_api_spell_check_client.cc",\n'
            '      "shell/renderer/api/electron_api_spell_check_client.h",\n'
            '    ]\n'
            '  }\n')
    web_frame = 'electron/shell/renderer/api/electron_api_web_frame.cc'
    replace(web_frame, '#include "components/spellcheck/renderer/spellcheck.h"\n'
            '#include "content/public/renderer/render_frame.h"',
            '#include "electron/buildflags/buildflags.h"\n'
            '#include "content/public/renderer/render_frame.h"')
    guard_region(web_frame, '#include "shell/renderer/api/electron_api_spell_check_client.h"',
                 '#include "shell/renderer/renderer_client_base.h"', 'ENABLE_BUILTIN_SPELLCHECKER')
    for first, until in (
        ('class SpellCheckerHolder;', 'class ScriptExecutionCallback'),
        ('class FrameSetSpellChecker :', 'class WebFrameRenderer final'),
        ('        .SetMethod("setSpellCheckProvider",', '        // Frame navigators'),
        ('  void SetSpellCheckProvider(', '  void InsertText('),
    ):
        guard_region(web_frame, first, until, 'ENABLE_BUILTIN_SPELLCHECKER')

    replace('gpu/ipc/service/gpu_init.cc',
            '    gl::SolidColorPoolFactory solid_color_factory;\n'
            '    if (dawn_context_provider_) {',
            '    gl::SolidColorPoolFactory solid_color_factory;\n'
            '#if BUILDFLAG(SKIA_USE_DAWN)\n'
            '    if (dawn_context_provider_) {')
    replace('gpu/ipc/service/gpu_init.cc',
            '      d3d12_command_queue = dawn_context_provider_->GetD3D12CommandQueue();\n'
            '#if BUILDFLAG(SKIA_USE_DAWN)\n',
            '      d3d12_command_queue = dawn_context_provider_->GetD3D12CommandQueue();\n')
    replace('gpu/ipc/service/gpu_init.cc',
            '#endif  // BUILDFLAG(SKIA_USE_DAWN)\n'
            '    } else {\n'
            '      d3d11_device = gl::QueryD3D11DeviceObjectFromANGLE();',
            '    } else\n'
            '#endif  // BUILDFLAG(SKIA_USE_DAWN)\n'
            '    {\n'
            '      d3d11_device = gl::QueryD3D11DeviceObjectFromANGLE();')
    replace('gpu/command_buffer/service/shared_image/d3d_image_backing_factory.cc',
            '    DawnContextProvider* dawn_context_provider /*=nullptr*/) {\n',
            '    DawnContextProvider* dawn_context_provider /*=nullptr*/) {\n'
            '#if BUILDFLAG(SKIA_USE_DAWN)\n')
    replace('gpu/command_buffer/service/shared_image/d3d_image_backing_factory.cc',
            '  return gl::DirectCompositionSupported() &&\n',
            '#endif\n\n  return gl::DirectCompositionSupported() &&\n')

    d3d = 'gpu/command_buffer/service/shared_image/d3d_image_'
    backing = d3d + 'backing.cc'
    header = d3d + 'backing.h'
    representation = d3d + 'representation.cc'
    representation_header = d3d + 'representation.h'
    replace(backing, '#include "gpu/command_buffer/service/dawn_context_provider.h"\n'
            '#include "gpu/command_buffer/service/dxgi_shared_handle_manager.h"',
            '#include "gpu/command_buffer/service/dxgi_shared_handle_manager.h"')
    replace(backing, '#include "gpu/command_buffer/service/shared_image/skia_graphite_dawn_image_representation.h"\n', '')
    for first, until in (
        ('// clang-format off\n#include <dawn/native/D3D11Backend.h>', '#include "base/functional/bind.h"'),
        ('Microsoft::WRL::ComPtr<ID3D11Device> GetD3D11Device(',
         'Microsoft::WRL::ComPtr<IDCompositionTexture> CreateDCompTexture('),
        ('// PersistentGraphiteDawnAccess. This is ref counted',
         '// static\nscoped_refptr<D3DImageBacking::GLTextureHolder>'),
        ('std::unique_ptr<DawnImageRepresentation> D3DImageBacking::ProduceDawn(',
         'Microsoft::WRL::ComPtr<ID3D12Resource> D3DImageBacking::EnsureD3D12Resource()'),
        ('wgpu::Texture D3DImageBacking::GetOrCreateDawnTexture(',
         'void D3DImageBacking::UpdateExternalFence('),
        ('int D3DImageBacking::TrackBeginAccessToWGPUTexture(', 'bool D3DImageBacking::BeginAccessD3D('),
        ('std::unique_ptr<DawnBufferRepresentation> D3DImageBacking::ProduceDawnBuffer(',
         'bool D3DImageBacking::ValidateBeginAccess('),
        ('void D3DImageBacking::FlushGraphiteCommandsIfNeeded()',
         'ID3D12CommandQueue* D3DImageBacking::GetOrCreateCommandQueueFor11On12()'),
        ('  // Flush any previously deferred Graphite commands before uploading',
         '  if (use_update_subresource1_'),
        ('  // Flush any previously deferred Graphite commands to ensure the readback',
         '  ID3D11Texture2D* staging_texture'),
        ('  if (persistent_graphite_dawn_access_) {\n'
         '    if (persistent_graphite_dawn_access_->IsGraphiteD3D11Device(d3d11_device))',
         '  // If the texture is currently unwrapped for D3D12,'),
        ('  if (in_write_access_) {\n    NotifyGraphiteAboutInitializedStatus();',
         '  EndAccessCommon(signaled_fence);'),
        ('  // Flush any deferred Graphite submits before presentation.', '  TRACE_EVENT1('),
    ):
        guard_dawn(backing, first, until)
    for line in (
        '    d3d12_shared_texture_memory_is_current_ = false;',
        '  FlushGraphiteCommandsIfNeeded();\n\n  if (!ValidateBeginAccess(write_access)) {',
    ):
        first, *rest = line.split('\n', 1)
        replace(backing, line + '\n', '#if BUILDFLAG(SKIA_USE_DAWN)\n' + first +
                '\n#endif  // BUILDFLAG(SKIA_USE_DAWN)\n' + (rest[0] + '\n' if rest else ''))
    replace(backing, ',\n      dawn_shared_texture_cache_(\n'
            '          base::MakeRefCounted<DawnSharedTextureCache>()) {\n', ' {\n')
    replace(backing, ',\n      dawn_shared_texture_cache_(\n'
            '          base::MakeRefCounted<DawnSharedTextureCache>()) {}\n', ' {}\n')
    replace(header, 'scoped_refptr<DawnSharedTextureCache> dawn_shared_texture_cache_\n'
            '      GUARDED_BY(lock_);',
            'scoped_refptr<DawnSharedTextureCache> dawn_shared_texture_cache_\n'
            '      GUARDED_BY(lock_) = base::MakeRefCounted<DawnSharedTextureCache>();')
    for first, until in (
        ('  std::unique_ptr<DawnImageRepresentation> ProduceDawn(', '  void UpdateExternalFence('),
        ('  wgpu::Texture BeginAccessDawn(', '  std::unique_ptr<WebNNTensorRepresentation> ProduceWebNNTensor('),
        ('  bool SupportsDeferredGraphiteSubmit() const;', '  // Holds a gles2::TexturePassthrough'),
        ('  void CheckForDawnDeviceLoss(', '  // Get a list of fences'),
        ('  // Uses either DXGISharedHandleState or internal', '  // Unwraps the D3D11 texture'),
        ('  // DawnSharedTextureCache that keeps', '  std::optional<base::WaitableEventWatcher>'),
        ('  // Persistent Graphite\'s Dawn\'s access.', '  base::WeakPtrFactory<D3DImageBacking>'),
    ):
        guard_dawn(header, first, until)
    guard_dawn(representation, 'DawnD3DImageRepresentation::DawnD3DImageRepresentation(',
               'WebNND3DTensorRepresentation::WebNND3DTensorRepresentation(')
    guard_dawn(representation, '// D3DSkiaGraphiteDawnImageRepresentation\n', '}  // namespace gpu')
    guard_dawn(representation_header,
               '#include "gpu/command_buffer/service/shared_image/skia_graphite_dawn_image_representation.h"\n',
               '#include "gpu/command_buffer/service/texture_manager.h"')
    guard_dawn(representation_header, '// Representation of a D3DImageBacking as a Dawn Texture',
               '// Representation of a D3DImageBacking as a tensor.')
    guard_dawn(representation_header, 'class D3DSkiaGraphiteDawnImageRepresentation', '}  // namespace gpu')

    replace('content/browser/devtools/features.gni',
            'enable_devtools_frontend = !is_ios && !is_fuchsia',
            'enable_devtools_frontend = false')
    replace('chrome/browser/devtools/BUILD.gn',
            'if (enable_devtools_frontend) {\n  import("//chrome/common/features.gni")',
            'import("//chrome/common/features.gni")\n\nif (enable_devtools_frontend) {')
    replace('electron/buildflags/BUILD.gn',
            'import("//build/buildflag_header.gni")',
            'import("//build/buildflag_header.gni")\n'
            'import("//content/browser/devtools/features.gni")')
    replace('electron/buildflags/BUILD.gn',
            '    "ENABLE_PDF_VIEWER=$enable_pdf_viewer",',
            '    "ENABLE_PDF_VIEWER=$enable_pdf_viewer",\n'
            '    "ENABLE_DEVTOOLS_FRONTEND=$enable_devtools_frontend",')
    inspectable = 'electron/shell/browser/ui/inspectable_web_contents.cc'
    bundle = 'electron/shell/browser/ui/devtools_ui_bundle_data_source.cc'
    for name, anchor in ((inspectable, '#include <algorithm>'),
                         (bundle, '#include <string>')):
        replace(name, anchor, '#include "electron/buildflags/buildflags.h"\n\n' + anchor)
    for first, until in (
        ('constexpr std::string_view kChromeUIDevToolsURL',
         'constexpr std::string_view kDevToolsBoundsPref'),
        ('GURL GetRemoteBaseURL()', 'constexpr base::TimeDelta kInitialBackoffDelay'),
        ('  if (embedder_message_dispatcher_) {\n    if (managed_devtools_web_contents_)\n'
         '      view_->ShowDevTools(activate);', '\n}\n'),
        ('  if (new_host->GetParent())', '\n}\n'),
        ('  if (navigation_handle->IsInPrimaryMainFrame()) {\n'
         '    if (navigation_handle->GetRenderFrameHost() ==', '\n}\n'),
    ):
        guard_region(inspectable, first, until, 'ENABLE_DEVTOOLS_FRONTEND')
    guard_region(bundle, 'std::string PathWithoutParams(',
                 'scoped_refptr<base::RefCountedMemory> CreateNotFoundResponse()',
                 'ENABLE_DEVTOOLS_FRONTEND')
    replace(bundle,
            '  std::string filename = PathWithoutParams(path);\n'
            '  scoped_refptr<base::RefCountedMemory> bytes =\n'
            '      content::DevToolsFrontendHost::GetFrontendResourceBytes(filename);',
            '  scoped_refptr<base::RefCountedMemory> bytes;\n'
            '#if BUILDFLAG(ENABLE_DEVTOOLS_FRONTEND)\n'
            '  std::string filename = PathWithoutParams(path);\n'
            '  bytes = content::DevToolsFrontendHost::GetFrontendResourceBytes(filename);')
    replace(bundle, '  std::move(callback).Run(bytes);',
            '#endif  // BUILDFLAG(ENABLE_DEVTOOLS_FRONTEND)\n'
            '  std::move(callback).Run(bytes);')
    replace('media/cdm/cdm_paths.h',
            '#if !BUILDFLAG(ENABLE_LIBRARY_CDMS)\n'
            '#error This file only applies to builds that enable_library_cdms.\n',
            '#if !BUILDFLAG(ENABLE_LIBRARY_CDMS) && !BUILDFLAG(IS_WIN)\n'
            '#error This file requires library CDMs or Windows.\n')
    replace('media/cdm/library_cdm/cdm_paths.gni',
            'assert(enable_library_cdms)', 'assert(enable_library_cdms || is_win)')
    replace('media/BUILD.gn',
            'if (enable_library_cdms) {\n  import("//media/cdm/library_cdm/cdm_paths.gni")',
            'if (enable_library_cdms || is_win) {\n  import("//media/cdm/library_cdm/cdm_paths.gni")')
    replace('media/BUILD.gn',
            '  if (enable_library_cdms) {\n    flags += [',
            '  if (enable_library_cdms || is_win) {\n    flags += [')
    replace('media/cdm/BUILD.gn',
            'if (enable_library_cdms) {\n  static_library("cdm_paths") {',
            'if (enable_library_cdms || is_win) {\n  static_library("cdm_paths") {')
    replace('printing/BUILD.gn',
            '  assert(enable_printing)',
            '  assert(enable_printing || enable_pdf)')
    replace('printing/BUILD.gn',
            '  if (!enable_basic_print_dialog) {',
            '  if (!enable_basic_print_dialog && !is_win) {')
    metafile = 'printing/common/metafile_utils.cc'
    for first, until in (
        ('SkString GetHeadingStructureType(', 'sk_sp<SkPicture> GetEmptyPicture()'),
        ('void AppendCheckedStateIfTrue(', 'sk_sp<const SkData> GetImageData('),
    ):
        guard_region(metafile, first, until, 'ENABLE_PRINTING')
    replace(metafile, '  SkPDF::Metadata metadata;',
            '#if BUILDFLAG(ENABLE_PRINTING)\n  SkPDF::Metadata metadata;')
    replace(metafile, '  return SkPDF::MakeDocument(stream, metadata);',
            '  return SkPDF::MakeDocument(stream, metadata);\n'
            '#else\n'
            '  return nullptr;\n'
            '#endif  // BUILDFLAG(ENABLE_PRINTING)')
    for anchor in (
        '      "$root_gen_dir/content/browser/devtools/devtools_resources.pak",\n',
        '      "//content/browser/devtools:devtools_resources",\n',
        '      "$root_gen_dir/chrome/accessibility_resources.pak",\n',
        '      "//chrome/browser/resources/accessibility:resources",\n',
        '      "$root_gen_dir/content/browser/webrtc/resources/webrtc_internals_resources.pak",\n',
        '      "//content/browser/webrtc/resources",\n',
        '      "$root_gen_dir/services/device/public/cpp/usb/usb_ids_resources.pak",\n',
        '      "//services/device/public/cpp/usb:usb_ids_resources",\n',
        '      "$root_gen_dir/content/service_worker_resources.pak",\n',
    ):
        replace('electron/build/electron_paks.gni', anchor, '')

    replace('third_party/blink/common/origin_trials/manual_completion_origin_trial_features.cc',
            '      blink::mojom::OriginTrialFeature::kXSLT,\n', '')
    name = 'content/child/runtime_features.cc'
    file = root / name
    text = file.read_text(encoding='utf-8')
    mappings = re.compile(r'(?m)^          \{wf::Enable(' + '|'.join(BLINK_FEATURES) +
                          r'),[^{}]*?\},\n')
    if not {'XSLT', 'WebUSB', 'WebXR', 'PaymentApp', 'SecurePaymentConfirmation'} <= set(mappings.findall(text)):
        raise RuntimeError(f'{name}: missing trimmed feature mappings')
    edits[file] = mappings.sub('', text)

    name = 'third_party/blink/renderer/platform/runtime_enabled_features.json5'
    file = root / name
    text = file.read_text(encoding='utf-8')
    for feature in BLINK_FEATURES:
        pattern = r'(\{\s*(?://[^\n]*\n\s*)*name:\s*"' + re.escape(feature) + r'",)(.*?)(\n    \},)'
        matches = list(re.finditer(pattern, text, re.S))
        if len(matches) != 1:
            raise RuntimeError('Missing or ambiguous Blink feature: ' + feature)
        match = matches[0]
        body = match[2]
        body = re.sub(r'\n\s*status:\s*(?:"[^"]*"|\{.*?\}),', '', body, count=1, flags=re.S)
        body = re.sub(r'\n\s*(?:base_feature|origin_trial_\w+):\s*[^\n]+,', '', body)
        body += '\n      base_feature: "none",'
        text = text[:match.start()] + match[1] + body + match[3] + text[match.end():]
    for feature in sorted({feature for _, feature in IDL_GATES.values()}):
        text = text.replace('  data: [', '  data: [\n    { name: "' + feature + '", },', 1)
    edits[file] = text
    for relative, (anchor, feature) in IDL_GATES.items():
        replace('third_party/blink/renderer/modules/' + relative, anchor,
                'RuntimeEnabled=' + feature + ',\n    ' + anchor)
    replace('third_party/blink/renderer/modules/peerconnection/rtc_peer_connection.idl',
            '    Exposed=Window,\n'
            '    LegacyWindowAlias=webkitRTCPeerConnection,\n'
            '    LegacyWindowAlias_Measure\n',
            '    Exposed=Window\n')
    replace('third_party/blink/renderer/core/exported/web_view_impl.cc',
            '  RuntimeEnabledFeatures::SetPaymentRequestEnabled(\n'
            '      prefs.payment_request_enabled);\n\n', '')

    replace('electron/BUILD.gn',
            'copy("chromium_licenses") {\n'
            '  deps = [ "//components/resources:about_credits" ]\n'
            '  sources = [ "$root_gen_dir/components/resources/about_credits.html" ]\n'
            '  outputs = [ "$root_build_dir/LICENSES.chromium.html" ]\n'
            '}',
            'action("chromium_licenses") {\n'
            '  script = "//tools/licenses/licenses.py"\n'
            '  outputs = [ "$root_build_dir/LICENSES.chromium.html" ]\n'
            '  data = outputs\n'
            '  depfile = "$target_gen_dir/chromium_licenses.d"\n'
            '  args = [\n'
            '    "credits",\n'
            '    "--target-os=win",\n'
            '    "--gn-out-dir=.",\n'
            '    "--gn-target=//electron:electron_app",\n'
            '    "--depfile=" + rebase_path(depfile, root_build_dir),\n'
            '    rebase_path(outputs[0], root_build_dir),\n'
            '  ]\n'
            '}')

    name = 'electron/shell/app/electron_main_delegate.cc'
    replace(name,
            '  auto* command_line = base::CommandLine::ForCurrentProcess();\n\n'
            '#if BUILDFLAG(IS_WIN)',
            '  auto* command_line = base::CommandLine::ForCurrentProcess();\n'
            '  command_line->AppendSwitch("disable-renderer-accessibility");\n\n'
            '#if BUILDFLAG(IS_WIN)')

    for file in root.rglob('BUILD.gn'):
        text = edits.get(file)
        if text is None:
            text = file.read_text(encoding='utf-8')
        gated = gate_trimmed_dependencies(text)
        if gated != text:
            edits[file] = gated

    for file, text in edits.items():
        file.write_text(text, encoding='utf-8', newline='\n')


def configure(root, output):
    patch(root)
    import importlib.util
    spec = importlib.util.spec_from_file_location('trim_icu', HERE / 'trim-icu.py')
    icu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(icu)
    data = Path(root) / 'third_party/icu/common/icudtl.dat'
    data.write_bytes(icu.trim(data.read_bytes()))
    file = Path(output) / 'args.gn'
    text = file.read_text(encoding='utf-8')
    file.write_text(text + '\n' + (HERE / 'trim-runtime.gn').read_text(encoding='utf-8'),
                    encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    configure(args.root, args.output)
    print('Applied Windows D3D11 runtime profile.')
