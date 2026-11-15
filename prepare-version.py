"""Restore and verify the release tag omitted by shallow gclient sync."""
from pathlib import Path
import subprocess
import sys


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args],
                                   text=True, encoding='utf-8').strip()


def prepare(root, version):
    tag = 'refs/tags/v' + version
    git(root, 'fetch', '--depth=1', '--no-tags', 'origin', tag + ':' + tag)
    if git(root, 'rev-parse', 'HEAD') != git(root, 'rev-parse', tag + '^{commit}'):
        raise RuntimeError('Electron checkout differs from release tag: ' + version)
    git(root, 'pack-refs', '--all')
    actual = subprocess.check_output([sys.executable, str(root / 'script/get-git-version.py')],
                                     text=True, encoding='utf-8').strip()
    if actual != version:
        raise RuntimeError(f'Electron version mismatch: expected {version}, got {actual}')
    print('Verified Electron release version: ' + actual, flush=True)


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), sys.argv[2])
