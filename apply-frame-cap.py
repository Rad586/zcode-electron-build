from pathlib import Path
import sys

root = Path(sys.argv[1])

def replace(path, old, new):
    file = root / path
    text = file.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise RuntimeError(f'{path}: expected exactly one patch anchor')
    file.write_text(text.replace(old, new), encoding='utf-8', newline='\n')

replace('shell/browser/api/electron_api_app.h',
        '  void DisableHardwareAcceleration(gin_helper::ErrorThrower thrower);',
        '  void SetFrameRateCap(gin_helper::ErrorThrower thrower, int frame_rate);\n'
        '  void DisableHardwareAcceleration(gin_helper::ErrorThrower thrower);')
replace('shell/browser/api/electron_api_app.cc',
        '#include "shell/app/command_line_args.h"',
        '#include "base/time/time.h"\n'
        '#include "content/public/browser/frame_rate_throttling.h"\n'
        '#include "shell/app/command_line_args.h"')
replace('shell/browser/api/electron_api_app.cc',
        'void App::DisableHardwareAcceleration(gin_helper::ErrorThrower thrower) {',
        '''void App::SetFrameRateCap(gin_helper::ErrorThrower thrower, int frame_rate) {
  if (!Browser::Get()->is_ready()) {
    thrower.ThrowError("app.setFrameRateCap() requires app to be ready");
    return;
  }
  if (frame_rate < 0 || frame_rate > 1000) {
    thrower.ThrowRangeError("Frame rate must be between 0 and 1000");
    return;
  }
  if (frame_rate == 0) {
    content::StopThrottlingAllFrameSinks();
  } else {
    content::StartThrottlingAllFrameSinks(base::Hertz(frame_rate));
  }
}

void App::DisableHardwareAcceleration(gin_helper::ErrorThrower thrower) {''')
replace('shell/browser/api/electron_api_app.cc',
        '      .SetMethod("disableHardwareAcceleration",',
        '      .SetMethod("setFrameRateCap", &App::SetFrameRateCap)\n'
        '      .SetMethod("disableHardwareAcceleration",')
print('Applied dynamic onscreen frame-rate cap to Electron app API.')
