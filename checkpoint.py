"""Preserve Ninja outputs and input timestamps between disposable runners."""
import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path('D:/ec/src')
CACHE = Path('D:/ec/checkpoint')


def inputs(root):
    for directory, folders, files in os.walk(root):
        if '.git' in folders:
            for name in ('HEAD', 'packed-refs'):
                reference = Path(directory) / '.git' / name
                if reference.is_file():
                    yield reference
        folders[:] = [name for name in folders if name not in ('.git', 'out', '__pycache__')
                      and not (Path(directory) / name).is_symlink()
                      and not os.path.isjunction(Path(directory) / name)]
        for name in files:
            file = Path(directory) / name
            if not file.is_symlink():
                yield file


def identity():
    revisions = subprocess.check_output(
        ['cmd.exe', '/d', '/c', 'D:\\depot_tools\\gclient.bat', 'revinfo', '--actual'],
        cwd=ROOT.parent, text=True, encoding='utf-8')
    depot = subprocess.check_output(['git', '-C', 'D:/depot_tools', 'rev-parse', 'HEAD'],
                                    text=True).strip()
    return {'schema': 1, 'source': os.environ['GITHUB_SHA'], 'depot': depot,
            'image': os.environ['ImageVersion'], 'revisions': sorted(revisions.splitlines()),
            'visualStudio': os.environ['vs2022_install'],
            'wrapper': os.environ['SCCACHE_PATH']}


def save(root, cache, current):
    cache.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with gzip.open(cache / 'inputs.json.gz', 'wt', encoding='utf-8') as output:
        for file in inputs(root):
            output.write(json.dumps([file.relative_to(root).as_posix(),
                                     file.stat().st_mtime_ns], separators=(',', ':')) + '\n')
    subprocess.run(['7z', 'a', '-t7z', '-mx=1', '-mmt=2', '-bsp0',
                    str(cache / 'outputs.7z'), 'out/Release'], cwd=root, check=True)
    if (cache / 'outputs.7z').stat().st_size > 7 * 1024 ** 3:
        print('Checkpoint exceeds the cache budget; retaining compiler cache only.', flush=True)
        return False
    # Publish metadata last so incomplete preparation cannot be restored.
    (cache / 'identity.json').write_text(json.dumps(current), encoding='utf-8')
    print(f'Build checkpoint prepared in {time.monotonic() - started:.1f}s', flush=True)
    return True


def restore(root, cache, current):
    metadata = cache / 'identity.json'
    if not metadata.exists():
        print('No complete build checkpoint; using compiler cache.', flush=True)
        return False
    if json.loads(metadata.read_text(encoding='utf-8')) != current:
        print('Checkpoint inputs or runner tools changed; using compiler cache.', flush=True)
        return False
    started = time.monotonic()
    paths = []
    with gzip.open(cache / 'inputs.json.gz', 'rt', encoding='utf-8') as source:
        for line in source:
            name, stamp = json.loads(line)
            relative = Path(name)
            if relative.is_absolute() or relative.drive or '..' in relative.parts:
                raise RuntimeError('Unsafe checkpoint input path: ' + name)
            paths.append((root / relative, stamp))
    if (root / 'out/Release/.ninja_log').exists():
        raise RuntimeError('Build output already exists before checkpoint restore')
    subprocess.run(['7z', 'x', '-y', '-bsp0', str(cache / 'outputs.7z'), '-o' + str(root)],
                   check=True)
    restored = 0
    for file, stamp in paths:
        if file.is_file() and not file.is_symlink():
            os.utime(file, ns=(file.stat().st_atime_ns, stamp))
            restored += 1
    print(f'Restored Ninja outputs and {restored} input timestamps in '
          f'{time.monotonic() - started:.1f}s', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['save', 'restore'])
    args = parser.parse_args()
    current = identity()
    if args.action == 'restore':
        restore(ROOT, CACHE, current)
    elif save(ROOT, CACHE, current):
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write('ready=true\n')


if __name__ == '__main__':
    main()
