from pathlib import Path
import sys


def patch(text):
    edits = [
        ("""  fs.lstatSync = (pathArgument: string, options: any) => {
    const pathInfo = splitPath(pathArgument);
    if (!pathInfo.isAsar) return lstatSync(pathArgument, options);
    const { asarPath, filePath } = pathInfo;
""", """  function statFromArchiveSync(pathInfo: Extract<SplitPathResult, { isAsar: true }>, options: any) {
    const { asarPath, filePath } = pathInfo;
"""),
        ("""    return asarStatsToFsStats(stats, options);
  };

  const { lstat } = fs;
""", """    return asarStatsToFsStats(stats, options);
  }

  fs.lstatSync = (pathArgument: string, options: any) => {
    const pathInfo = splitPath(pathArgument);
    return pathInfo.isAsar ? statFromArchiveSync(pathInfo, options) : lstatSync(pathArgument, options);
  };

  const { lstat } = fs;
"""),
        ("""  fs.lstat = (pathArgument: string, options: any, callback: any) => {
    const pathInfo = splitPath(pathArgument);
    if (typeof options === 'function') {
      callback = options;
      options = {};
    }
    if (!pathInfo.isAsar) return lstat(pathArgument, options, callback);
    const { asarPath, filePath } = pathInfo;
""", """  function statFromArchive(pathInfo: Extract<SplitPathResult, { isAsar: true }>, options: any, callback: any) {
    const { asarPath, filePath } = pathInfo;
"""),
        ("""    nextTick(callback, [null, fsStats]);
  };

  fs.promises.lstat = util.promisify(fs.lstat);
""", """    nextTick(callback, [null, fsStats]);
  }

  fs.lstat = (pathArgument: string, options: any, callback: any) => {
    const pathInfo = splitPath(pathArgument);
    if (typeof options === 'function') {
      callback = options;
      options = {};
    }
    if (!pathInfo.isAsar) return lstat(pathArgument, options, callback);
    statFromArchive(pathInfo, options, callback);
  };

  fs.promises.lstat = util.promisify(fs.lstat);
"""),
        ("""    const { isAsar } = splitPath(pathArgument);
    if (!isAsar) return statSync(pathArgument, options);

    // Do not distinguish links for now.
    return fs.lstatSync(pathArgument, options);
""", """    const pathInfo = splitPath(pathArgument);
    if (!pathInfo.isAsar) return statSync(pathArgument, options);

    // Do not distinguish links for now.
    return statFromArchiveSync(pathInfo, options);
"""),
        ("""    const { isAsar } = splitPath(pathArgument);
    if (typeof options === 'function') {
      callback = options;
      options = {};
    }
    if (!isAsar) return stat(pathArgument, options, callback);

    // Do not distinguish links for now.
    process.nextTick(() => fs.lstat(pathArgument, options, callback));
""", """    const pathInfo = splitPath(pathArgument);
    if (typeof options === 'function') {
      callback = options;
      options = {};
    }
    if (!pathInfo.isAsar) return stat(pathArgument, options, callback);

    // Do not distinguish links for now.
    process.nextTick(() => statFromArchive(pathInfo, options, callback));
"""),
    ]
    for old, new in edits:
        if text.count(old) != 1:
            raise RuntimeError('Expected exactly one ASAR stat patch anchor: ' + old.splitlines()[0])
        text = text.replace(old, new)
    return text


if __name__ == '__main__':
    file = Path(sys.argv[1]) / 'lib/node/asar-fs-wrapper.ts'
    source = file.read_text(encoding='utf-8')
    updated = patch(source)
    file.write_text(updated, encoding='utf-8', newline='\n')
    print('Applied single-pass ASAR stat dispatch.')
