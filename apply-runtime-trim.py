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


def patch(root):
    root = Path(root)
    edits = {}

    def replace(name, old, new):
        file = root / name
        text = edits.get(file, file.read_text(encoding='utf-8'))
        if text.count(old) != 1:
            raise RuntimeError(f'{name}: expected one patch anchor: {old[:70]}')
        edits[file] = text.replace(old, new)

    replace('build/config/locales.gni',
            'locales_without_pseudolocales = platform_pak_locales - pseudolocales',
            'if (is_win) {\n'
            '  platform_pak_locales = []\n'
            '  platform_pak_locales = [ "en-US", "zh-CN", "zh-TW" ]\n'
            '}\n\nlocales_without_pseudolocales = platform_pak_locales - pseudolocales')
    replace('components/spellcheck/spellcheck_build_features.gni',
            'enable_spellcheck = use_blink', 'enable_spellcheck = false')

    replace('content/browser/devtools/features.gni',
            'enable_devtools_frontend = !is_ios && !is_fuchsia',
            'enable_devtools_frontend = false')
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
