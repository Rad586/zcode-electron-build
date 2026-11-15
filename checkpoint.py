"""Preserve Ninja outputs and input timestamps between disposable runners."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
LEGACY_SOURCE = '4dbfd300a0041b5eef4faf03c6674f0192e1ba89'
PATCH_SCRIPTS = ('apply-frame-cap.py', 'apply-asar-stat.py', 'apply-svg-lifecycle.py',
                 'apply-runtime-trim.py', 'trim-icu.py', 'trim-runtime.gn')

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


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args],
                                   text=True, encoding='utf-8').strip()


def revision_identity(root, revisions):
    stable = {}
    for name, entry in revisions.items():
        repo = root.parent / name
        if (repo / '.git').exists():
            # Electron's git am creates different commit IDs for identical patched trees.
            entry = dict(entry, rev=git(repo, 'rev-parse', 'HEAD^{tree}'))
        stable[name] = entry
    return stable


def input_content(file):
    with file.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def identity():
    with tempfile.TemporaryDirectory(prefix='checkpoint-revisions-', dir=ROOT.parent) as work:
        output = Path(work) / 'revisions.json'
        subprocess.run(['cmd.exe', '/d', '/c', 'D:\\depot_tools\\gclient.bat',
                        'revinfo', '--actual', '--output-json', str(output)],
                       cwd=ROOT.parent, check=True)
        revisions = json.loads(output.read_text(encoding='utf-8'))
    return {'schema': 3, 'args': (ROOT / 'out/Release/args.gn').read_text(encoding='utf-8'),
            'patches': {name: (HERE / name).read_text(encoding='utf-8')
                        for name in PATCH_SCRIPTS},
            'depot': git('D:/depot_tools', 'rev-parse', 'HEAD'),
            'image': os.environ['ImageVersion'],
            'revisions': revision_identity(ROOT, revisions),
            'visualStudio': os.environ['vs2022_install'],
            'wrapper': os.environ['SCCACHE_PATH']}


def legacy_compatible(root, saved, current):
    if saved.get('source') != LEGACY_SOURCE:
        return False
    if any(saved.get(key) != current.get(key)
           for key in ('depot', 'image', 'visualStudio', 'wrapper')):
        return False
    # Only this known build recipe can migrate its pre-tree-identity checkpoint.
    git(HERE, 'fetch', '--depth=1', 'origin', LEGACY_SOURCE)
    if any(git(HERE, 'show', LEGACY_SOURCE + ':' + name) != text.strip()
           for name, text in current['patches'].items()):
        return False
    targets = json.loads((root / 'electron/patches/config.json').read_text(encoding='utf-8'))
    patched = {entry['repo'] for entry in targets
               if (root.parent / entry['repo'] / '.git').exists()}
    previous = {}
    for line in saved.get('revisions', []):
        if ': ' not in line or not line.startswith('src'):
            continue
        name, value = line.split(': ', 1)
        if value == 'None':
            previous[name] = {'url': None, 'rev': None}
            continue
        url, separator, revision = value.partition('@')
        previous[name] = {'url': url, 'rev': revision if separator else None}
    if previous.keys() != current['revisions'].keys():
        return False
    for name, entry in previous.items():
        now = current['revisions'][name]
        if entry['url'] != now['url']:
            return False
        repo = root.parent / name
        if (repo / '.git').exists():
            if name not in patched and entry['rev'] != git(repo, 'rev-parse', 'HEAD'):
                return False
        elif entry != now:
            return False
    print('Migrating legacy checkpoint with the same pinned Electron patch recipe.', flush=True)
    return True


def compatible(root, saved, current):
    if saved == current:
        return True
    changed = sorted(key for key in saved.keys() | current.keys()
                     if saved.get(key) != current.get(key))
    print('Checkpoint identity differences: ' + ', '.join(changed), flush=True)
    if current.get('schema') == 3:
        if saved.get('schema') == 2:
            return dict(saved, schema=3) == current
        if saved.get('schema') == 3:
            fixed = (saved.keys() | current.keys()) - {'patches', 'revisions'}
            if any(saved.get(key) != current.get(key) for key in fixed):
                return False
            old, new = saved['revisions'], current['revisions']
            if old.keys() != new.keys():
                return False
            for name in old:
                repo = root.parent / name
                if name in ('src', 'src/electron') and (repo / '.git').exists():
                    if old[name].get('url') != new[name].get('url'):
                        return False
                elif old[name] != new[name]:
                    return False
            return True
    if saved.get('schema') == 1 and current.get('schema') in (2, 3):
        return legacy_compatible(root, saved, current)
    return False


def save(root, cache, current):
    cache.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with gzip.open(cache / 'inputs.json.gz', 'wt', encoding='utf-8') as output:
        for file in inputs(root):
            record = [file.relative_to(root).as_posix(), file.stat().st_mtime_ns]
            if current.get('schema') == 3:
                record.append(input_content(file))
            output.write(json.dumps(record, separators=(',', ':')) + '\n')
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
    saved = json.loads(metadata.read_text(encoding='utf-8'))
    if not compatible(root, saved, current):
        print('Checkpoint inputs or runner tools changed; using compiler cache.', flush=True)
        return False
    if 'args' in current:
        archived_args = subprocess.check_output(
            ['7z', 'e', '-so', str(cache / 'outputs.7z'), 'out/Release/args.gn'],
            text=True, encoding='utf-8')
        if archived_args != current['args']:
            print('Checkpoint GN arguments changed; using compiler cache.', flush=True)
            return False
    started = time.monotonic()
    paths = {}
    with gzip.open(cache / 'inputs.json.gz', 'rt', encoding='utf-8') as source:
        for line in source:
            record = json.loads(line)
            if len(record) != (3 if saved.get('schema') == 3 else 2):
                raise RuntimeError('Invalid checkpoint input record')
            name, stamp = record[:2]
            relative = Path(name)
            if relative.is_absolute() or relative.drive or '..' in relative.parts:
                raise RuntimeError('Unsafe checkpoint input path: ' + name)
            paths[root / relative] = (stamp, record[2] if len(record) == 3 else None)
    if (root / 'out/Release/.ninja_log').exists():
        raise RuntimeError('Build output already exists before checkpoint restore')
    subprocess.run(['7z', 'x', '-y', '-bsp0', str(cache / 'outputs.7z'), '-o' + str(root)],
                   check=True)
    restored, changed = 0, 0
    newest_output = max(file.stat().st_mtime_ns
                        for file in (root / 'out/Release').rglob('*') if file.is_file())
    changed_stamp = max(time.time_ns(), newest_output + 1_000_000)
    for file in inputs(root):
        previous = paths.get(file)
        if previous is not None:
            stamp, content = previous
            if content is None or input_content(file) == content:
                os.utime(file, ns=(file.stat().st_atime_ns, stamp))
                restored += 1
                continue
        os.utime(file, ns=(file.stat().st_atime_ns,
                           max(file.stat().st_mtime_ns, changed_stamp)))
        changed += 1
    print(f'Restored Ninja outputs and {restored} input timestamps in '
          f'{time.monotonic() - started:.1f}s; {changed} changed inputs retained', flush=True)
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
