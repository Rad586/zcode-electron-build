"""Exercise checkpoint restoration with isolated synthetic build inputs."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('checkpoint', HERE / 'checkpoint.py')
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        original_output = checkpoint.subprocess.check_output

        def check_output(command, **kwargs):
            if command[0] == '7z' and os.environ.get('ZCODE_TEST_7Z'):
                command = [os.environ['ZCODE_TEST_7Z'], *command[1:]]
            return original_output(command, **kwargs)

        self.output_patch = patch.object(checkpoint.subprocess, 'check_output', side_effect=check_output)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)
        self.work = Path(tempfile.mkdtemp(prefix='checkpoint-', dir=HERE))
        self.root = self.work / 'src'
        self.cache = self.work / 'cache'
        self.root.mkdir()
        self.identity = {'schema': 2, 'args': 'target_cpu = "x64"\n'}
        self.input = self.root / 'input.cc'
        self.input.write_text('int value;', encoding='utf-8')
        os.utime(self.input, ns=(1600000000123456700, 1600000000123456700))
        self.output = self.root / 'out/Release'
        self.output.mkdir(parents=True)
        (self.output / 'args.gn').write_text(self.identity['args'], encoding='utf-8')
        (self.output / '.ninja_log').write_text('ninja log', encoding='utf-8')
        (self.output / '.ninja_deps').write_bytes(b'dependencies')
        (self.output / 'value.obj').write_bytes(b'object')

    def tearDown(self):
        def remove_readonly(function, path, error):
            os.chmod(path, 0o700)
            function(path)
        shutil.rmtree(self.work, onexc=remove_readonly)

    def test_roundtrip(self):
        executable = os.environ.get('ZCODE_TEST_7Z')
        if not executable:
            self.skipTest('ZCODE_TEST_7Z is not configured')
        original = checkpoint.subprocess.run

        def run(command, **kwargs):
            return original([executable, *command[1:]], **kwargs)

        stamp = self.input.stat().st_mtime_ns
        with patch.object(checkpoint.subprocess, 'run', side_effect=run):
            checkpoint.save(self.root, self.cache, self.identity)
            shutil.rmtree(self.root / 'out')
            self.input.touch()
            self.assertTrue(checkpoint.restore(self.root, self.cache, self.identity))
        self.assertEqual(self.input.stat().st_mtime_ns, stamp)
        self.assertEqual((self.output / 'value.obj').read_bytes(), b'object')
        self.assertEqual((self.output / '.ninja_deps').read_bytes(), b'dependencies')

    def test_ninja_has_no_work_after_restore(self):
        executable = os.environ.get('ZCODE_TEST_7Z')
        ninja = os.environ.get('ZCODE_TEST_NINJA')
        if not executable or not ninja:
            self.skipTest('Archive tool and Ninja are required')
        shutil.rmtree(self.output)
        self.output.mkdir()
        (self.output / 'args.gn').write_text(self.identity['args'], encoding='utf-8')
        (self.output / 'build.ninja').write_text(
            f'rule copy\n  command = "{sys.executable}" -c '
            '\"import shutil; shutil.copyfile(\'../../input.cc\', \'value.obj\')\"\n'
            'build value.obj: copy ../../input.cc\n', encoding='utf-8')
        original = checkpoint.subprocess.run
        original([ninja, '-C', str(self.output)], check=True)

        def run(command, **kwargs):
            return original([executable, *command[1:]], **kwargs)

        with patch.object(checkpoint.subprocess, 'run', side_effect=run):
            checkpoint.save(self.root, self.cache, self.identity)
            shutil.rmtree(self.root / 'out')
            self.input.touch()
            checkpoint.restore(self.root, self.cache, self.identity)
        result = original([ninja, '-C', str(self.output)], check=True,
                          capture_output=True, text=True)
        self.assertIn('no work to do', result.stdout)

    def test_partial_build_continues_without_rebuilding_completed_target(self):
        executable = os.environ.get('ZCODE_TEST_7Z')
        ninja = os.environ.get('ZCODE_TEST_NINJA')
        if not executable or not ninja:
            self.skipTest('Archive tool and Ninja are required')
        shutil.rmtree(self.output)
        self.output.mkdir()
        (self.output / 'args.gn').write_text(self.identity['args'], encoding='utf-8')
        (self.output / 'build.ninja').write_text(
            f'rule copy\n  command = "{sys.executable}" -c '
            '\"import shutil; shutil.copyfile(\'../../input.cc\', \'$out\')\"\n'
            'build first.obj: copy ../../input.cc\n'
            'build second.obj: copy ../../input.cc\n', encoding='utf-8')
        original = checkpoint.subprocess.run
        original([ninja, '-C', str(self.output), 'first.obj'], check=True)
        stamp = (self.output / 'first.obj').stat().st_mtime_ns

        def run(command, **kwargs):
            return original([executable, *command[1:]], **kwargs)

        with patch.object(checkpoint.subprocess, 'run', side_effect=run):
            checkpoint.save(self.root, self.cache, self.identity)
            shutil.rmtree(self.root / 'out')
            self.input.touch()
            self.assertTrue(checkpoint.restore(self.root, self.cache, self.identity))
        result = original([ninja, '-C', str(self.output)], check=True,
                          capture_output=True, text=True)
        self.assertIn('[1/1]', result.stdout)
        self.assertIn('second.obj', result.stdout)
        self.assertEqual((self.output / 'first.obj').stat().st_mtime_ns, stamp)

    def test_missing_or_changed_checkpoint_uses_compiler_cache(self):
        self.assertFalse(checkpoint.restore(self.root, self.cache, self.identity))
        self.cache.mkdir()
        (self.cache / 'identity.json').write_text(json.dumps({'source': 'other'}), encoding='utf-8')
        with patch.object(checkpoint.subprocess, 'run') as run:
            self.assertFalse(checkpoint.restore(self.root, self.cache, self.identity))
            run.assert_not_called()

    def test_tree_identity_ignores_commit_time(self):
        original = checkpoint.subprocess.run
        original(['git', 'init', str(self.root)], check=True, capture_output=True)
        command = ['git', '-C', str(self.root), '-c', 'user.name=Test',
                   '-c', 'user.email=test@example.invalid', '-c', 'commit.gpgsign=false']
        original([*command, 'add', 'input.cc'], check=True, capture_output=True)
        revisions = {'src': {'url': 'https://example.invalid/src', 'rev': 'unused'}}
        identities, commits = [], []
        for date in ('2001-01-01T00:00:00+0000', '2002-01-01T00:00:00+0000'):
            env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
            action = ['commit', '-m', 'same'] if not commits else ['commit', '--amend', '--no-edit']
            original([*command, *action], env=env, check=True, capture_output=True)
            commits.append(checkpoint.git(self.root, 'rev-parse', 'HEAD'))
            identities.append(checkpoint.revision_identity(self.root, revisions))
        self.assertNotEqual(*commits)
        self.assertEqual(*identities)
        self.input.write_text('int changed;', encoding='utf-8')
        original([*command, 'add', 'input.cc'], check=True, capture_output=True)
        original([*command, 'commit', '-m', 'changed'], check=True, capture_output=True)
        self.assertNotEqual(identities[0], checkpoint.revision_identity(self.root, revisions))

    def test_identity_rejection_names_changed_fields(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertFalse(checkpoint.compatible(self.root,
                {'schema': 2, 'image': 'old'}, {'schema': 2, 'image': 'new'}))
        self.assertIn('identity differences: image', output.getvalue())

    def test_legacy_migration_checks_recipe_and_dependencies(self):
        (self.root / '.git').mkdir()
        electron = self.root / 'electron'
        (electron / '.git').mkdir(parents=True)
        (electron / 'patches').mkdir()
        (electron / 'patches/config.json').write_text(
            json.dumps([{'repo': 'src', 'patch_dir': 'src/electron/patches/chromium'}]),
            encoding='utf-8')
        current = {'schema': 2, 'patches': {'apply-frame-cap.py': 'same\n'},
                   'revisions': {'src': {'url': 'https://example.invalid/src', 'rev': 'tree'},
                                 'src/electron': {'url': 'https://example.invalid/electron', 'rev': 'tree'}}}
        saved = {'schema': 1, 'source': checkpoint.LEGACY_SOURCE,
                 'revisions': ['src: https://example.invalid/src@old-patched-commit',
                               'src/electron: https://example.invalid/electron@pinned']}

        def git(repo, *args):
            return 'same' if args[0] == 'show' else 'pinned'

        with patch.object(checkpoint, 'git', side_effect=git):
            self.assertTrue(checkpoint.compatible(self.root, saved, current))
            saved['revisions'][1] = 'src/electron: https://example.invalid/electron@changed'
            self.assertFalse(checkpoint.compatible(self.root, saved, current))
            saved['revisions'][1] = 'src/electron: https://example.invalid/electron@pinned'
            current['patches']['apply-frame-cap.py'] = 'changed'
            self.assertFalse(checkpoint.compatible(self.root, saved, current))

    def test_changed_gn_arguments_reject_archive_before_extraction(self):
        self.cache.mkdir()
        current = {'schema': 2, 'args': 'target_cpu = "x64"\n'}
        (self.cache / 'identity.json').write_text(json.dumps(current), encoding='utf-8')
        with patch.object(checkpoint.subprocess, 'check_output', return_value='different'), \
                patch.object(checkpoint.subprocess, 'run') as run:
            self.assertFalse(checkpoint.restore(self.root, self.cache, current))
            run.assert_not_called()

    def test_inputs_exclude_outputs_and_git(self):
        (self.root / '.git').mkdir()
        (self.root / '.git/config').write_text('private', encoding='utf-8')
        self.assertEqual(list(checkpoint.inputs(self.root)), [self.input])

    def test_failed_archive_does_not_publish_metadata(self):
        with patch.object(checkpoint.subprocess, 'run', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                checkpoint.save(self.root, self.cache, self.identity)
        self.assertFalse((self.cache / 'identity.json').exists())


if __name__ == '__main__':
    unittest.main()
