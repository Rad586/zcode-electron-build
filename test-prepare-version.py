"""Check release version recovery with real shallow Git clones and Ninja."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('prepare_version', HERE / 'prepare-version.py')
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='version-test-', dir=HERE))
        self.origin = self.work / 'origin'
        self.origin.mkdir()
        self.command('git', 'init', str(self.origin))
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        (self.origin / 'script').mkdir()
        upstream = HERE.parent / 'electron-44.10.2/script/get-git-version.py'
        shutil.copyfile(upstream, self.origin / 'script/get-git-version.py')
        self.git('add', '.')
        self.git('commit', '-m', 'Release')
        self.git('tag', 'v44.10.2')
        self.clone = self.work / 'clone'

    def tearDown(self):
        def remove_readonly(function, path, error):
            os.chmod(path, 0o700)
            function(path)
        shutil.rmtree(self.work, onexc=remove_readonly)

    def command(self, *args):
        return subprocess.check_output(list(args), text=True, encoding='utf-8',
                                       stderr=subprocess.STDOUT).strip()

    def git(self, *args):
        return self.command('git', '-C', str(self.origin), *args)

    def shallow_clone(self):
        self.command('git', 'clone', '--depth=1', '--no-tags', self.origin.as_uri(), str(self.clone))

    def actual(self):
        return self.command(sys.executable, str(self.clone / 'script/get-git-version.py'))

    def test_shallow_release_tag_recovers_version_without_changing_tree(self):
        self.shallow_clone()
        self.assertEqual(self.actual(), '0.0.0-no-git-tag-found')
        before = version.git(self.clone, 'rev-parse', 'HEAD^{tree}')
        version.prepare(self.clone, '44.10.2')
        self.assertEqual(self.actual(), '44.10.2')
        self.assertEqual(version.git(self.clone, 'rev-parse', 'HEAD^{tree}'), before)
        self.assertIn('refs/tags/v44.10.2', (self.clone / '.git/packed-refs').read_text())

    def test_wrong_checkout_is_rejected(self):
        (self.origin / 'changed').write_text('changed', encoding='utf-8')
        self.git('add', '.')
        self.git('commit', '-m', 'Different checkout')
        self.shallow_clone()
        with self.assertRaisesRegex(RuntimeError, 'differs from release tag'):
            version.prepare(self.clone, '44.10.2')

    def test_updated_version_graph_reuses_unaffected_ninja_outputs(self):
        ninja = os.environ.get('ZCODE_TEST_NINJA')
        if not ninja:
            self.skipTest('ZCODE_TEST_NINJA is not configured')
        self.shallow_clone()
        graph = self.work / 'build.ninja'

        def generate(value):
            graph.write_text(
                f'rule version\n  command = "{sys.executable}" -c '
                f'"from pathlib import Path; Path(\'version\').write_text(\'{value}\')"\n'
                f'rule object\n  command = "{sys.executable}" -c '
                '"from pathlib import Path; Path(\'unchanged.obj\').write_text(\'object\')"\n'
                'build version: version\nbuild unchanged.obj: object\n', encoding='utf-8')

        generate(self.actual())
        self.command(ninja, '-C', str(self.work))
        stamp = (self.work / 'unchanged.obj').stat().st_mtime_ns
        version.prepare(self.clone, '44.10.2')
        generate(self.actual())
        result = self.command(ninja, '-C', str(self.work))
        self.assertIn('[1/1]', result)
        self.assertEqual((self.work / 'version').read_text(), '44.10.2')
        self.assertEqual((self.work / 'unchanged.obj').stat().st_mtime_ns, stamp)


if __name__ == '__main__':
    unittest.main()
