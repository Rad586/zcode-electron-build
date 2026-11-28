"""Apply or stage the ASAR promise read adapter experiment."""

import argparse
import os
from pathlib import Path
import stat
import tempfile


UTIL_ANCHOR = "const { assignFunctionName } = __non_webpack_require__('internal/util') as typeof import('@node/lib/internal/util');"
UTIL_REPLACEMENT = '''const {
  assignFunctionName, customPromisifyArgs, promisify: defaultPromisify
} = __non_webpack_require__('internal/util') as {
  assignFunctionName: typeof import('@node/lib/internal/util').assignFunctionName;
  customPromisifyArgs: symbol;
  promisify: typeof util.promisify;
};
const customPromisified = Symbol.for('nodejs.util.promisify.custom');'''

ANCHOR = '''  const { readFile: readFilePromise } = fs.promises;
  fs.promises.readFile = function (pathArgument: string, options: any) {
    const pathInfo = splitPath(pathArgument);
    if (!pathInfo.isAsar) {
      return readFilePromise.apply(this, arguments);
    }

    const p = util.promisify(fsReadFileAsar);
    return p(pathArgument, options);
  };'''


REPLACEMENT = ANCHOR.replace(
    '  fs.promises.readFile =',
    '  let readFileAsarPromise: ((pathArgument: string, options: any) => Promise<any>) | undefined;\n'
    '  fs.promises.readFile =',
).replace(
    '    const p = util.promisify(fsReadFileAsar);',
    '''    const promisify = util.promisify;
    // Reuse only the stock adapter for our private callback without custom hooks.
    const p = promisify === defaultPromisify &&
        !(customPromisified in fsReadFileAsar) && !(customPromisifyArgs in fsReadFileAsar)
      ? (readFileAsarPromise ??= promisify(fsReadFileAsar))
      : Reflect.apply(promisify, util, [fsReadFileAsar]);''',
)


def patch(source):
    for anchor, replacement in ((UTIL_ANCHOR, UTIL_REPLACEMENT), (ANCHOR, REPLACEMENT)):
        if source.count(anchor) != 1:
            raise ValueError('Expected exactly one ASAR patch anchor: ' + anchor.splitlines()[0])
        source = source.replace(anchor, replacement)
    return source


def apply_at(root):
    source = root / 'lib/node/asar-fs-wrapper.ts'
    updated = patch(source.read_text(encoding='utf-8'))
    file = tempfile.NamedTemporaryFile('w', dir=source.parent, prefix='.startup-asar-read-20261128-',
                                       encoding='utf-8', newline='\n', delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(updated)
        temporary.chmod(stat.S_IMODE(source.stat().st_mode))
        os.replace(temporary, source)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Electron source root, or wrapper file in stage mode')
    parser.add_argument('output', type=Path, nargs='?', help='New staged .ts file; leaves source unmodified')
    args = parser.parse_args()
    if args.output is None:
        apply_at(args.source)
        print('Applied guarded ASAR promise read adapter reuse.')
        return
    updated = patch(args.source.read_text(encoding='utf-8'))
    with args.output.open('x', encoding='utf-8', newline='\n') as file:
        file.write(updated)


if __name__ == '__main__':
    main()
