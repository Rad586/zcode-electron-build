const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {performance} = require('node:perf_hooks');
const {stripTypeScriptTypes} = require('node:module');
const {internalBinding} = require('internal/test/binding');
const inspector = require('node:inspector');

const [sourceFile, fixture, output] = process.argv.slice(2);
const originalFs = require('original-fs');
let source = originalFs.readFileSync(sourceFile, 'utf8')
  .replace(/^import \{ Buffer \} from 'buffer';$/m, "const {Buffer} = require('buffer');")
  .replace(/^import \{ Dirent, constants \} from 'fs';$/m, "const {Dirent, constants} = require('fs');")
  .replace(/^import \* as (path|util) from '(path|util)';$/gm, 'const $1 = require(\'$2\');')
  .replace('export const wrapFsWithAsar', 'const wrapFsWithAsar');
source += '\nmodule.exports = wrapFsWithAsar;';
const nativeAsar = process._linkedBinding('electron_common_asar');
let splits = 0;
const countedAsar = {...nativeAsar, splitPath(...args) { splits++; return nativeAsar.splitPath(...args); }};
const fakeBindings = new Map();
const fakeProcess = Object.create(process);
fakeProcess.internalBinding = name => {
  if (!fakeBindings.has(name)) fakeBindings.set(name, {...internalBinding(name)});
  return fakeBindings.get(name);
};
fakeProcess._linkedBinding = name => name === 'electron_common_asar' ? countedAsar : process._linkedBinding(name);
const fakeModule = {_extensions: {...require('node:module')._extensions}};
const childProcess = {...require('node:child_process')};
const localRequire = name => name === 'module' ? fakeModule : name === 'child_process' ? childProcess : require(name);
const moduleResult = {exports: {}};
const compiled = stripTypeScriptTypes(source, {mode: 'transform'});
vm.runInThisContext('(function(require, module, process, __non_webpack_require__) {' + compiled + '\n})', {filename: sourceFile})(localRequire, moduleResult, fakeProcess, require);
const wrapped = {...originalFs, promises: {...originalFs.promises}};
moduleResult.exports(wrapped);
const file = path.join(fixture, 'dir1', 'file1');
const missing = path.join(fixture, 'missing');
const normalize = stat => stat && Object.fromEntries(Object.entries(stat).filter(([key]) => key !== 'ino' && !/^(a|m|c|birth)time/.test(key)));
const cases = [file, path.join(fixture, 'dir1'), path.join(fixture, 'link1'), missing, path.join(fixture, 'dir1', '..', 'file1')];
let checks = 0;
function outcome(fn) {
  try { return {value: normalize(fn())}; }
  catch (error) { return {error: error.code, message: error.message}; }
}
const asyncStat = (owner, name, value, options) => new Promise(resolve => {
  let sync = true;
  owner[name](value, options, (error, stat) => {
    assert.equal(sync, false);
    resolve(error ? {error: error.code, message: error.message} : {value: normalize(stat)});
  });
  sync = false;
});
async function main() {
  for (const target of cases.flatMap(value => [value, Buffer.from(value)])) {
    for (const options of [undefined, {bigint: true}, {throwIfNoEntry: false}]) {
      for (const name of ['statSync', 'lstatSync']) {
        assert.deepEqual(outcome(() => wrapped[name](target, options)), outcome(() => fs[name](target, options)));
        checks++;
      }
      for (const name of ['stat', 'lstat']) {
        assert.deepEqual(await asyncStat(wrapped, name, target, options), await asyncStat(fs, name, target, options));
        checks++;
      }
    }
  }
  for (const name of ['stat', 'lstat']) {
    assert.deepEqual(normalize(await wrapped.promises[name](file)), normalize(await fs.promises[name](file)));
    await assert.rejects(wrapped.promises[name](missing), {code: 'ENOENT'});
    checks += 2;
  }
  fakeProcess.noAsar = true;
  assert.equal(wrapped.statSync(fixture).isFile(), true);
  assert.deepEqual(outcome(() => wrapped.statSync(file)), outcome(() => originalFs.statSync(file)));
  fakeProcess.noAsar = false;
  checks += 2;
  for (const target of [sourceFile, path.dirname(sourceFile), require('node:url').pathToFileURL(sourceFile), path.join(path.dirname(sourceFile), 'absent'), path.join(sourceFile, 'child')]) {
    for (const options of [undefined, {bigint: true}, {throwIfNoEntry: false}]) {
      for (const name of ['statSync', 'lstatSync']) {
        assert.deepEqual(outcome(() => wrapped[name](target, options)), outcome(() => fs[name](target, options)));
        checks++;
      }
      for (const name of ['stat', 'lstat']) {
        assert.deepEqual(await asyncStat(wrapped, name, target, options), await asyncStat(fs, name, target, options));
        checks++;
      }
    }
  }
  for (const target of [file, path.join(fixture, 'dir1'), path.join(fixture, 'link1')]) {
    const actual = wrapped.statSync(target);
    const expected = fs.statSync(target);
    for (const predicate of ['isFile', 'isDirectory', 'isSymbolicLink', 'isBlockDevice', 'isCharacterDevice', 'isFIFO', 'isSocket']) {
      assert.equal(actual[predicate](), expected[predicate]());
      checks++;
    }
    assert(actual.mtime instanceof Date);
    assert.equal(actual.mtimeMs, wrapped.statSync(target).mtimeMs);
    assert(Math.abs(actual.mtimeMs - Number(wrapped.statSync(target, {bigint: true}).mtimeNs) / 1e6) < 0.001);
    checks += 3;
  }
  for (const name of ['stat', 'lstat']) {
    assert.deepEqual(await asyncStat(wrapped, name, file), await asyncStat(fs, name, file));
    const omitted = owner => new Promise(resolve => owner[name](file, (error, stat) => resolve(error ? {error: error.code} : {value: normalize(stat)})));
    assert.deepEqual(await omitted(wrapped), await omitted(fs));
    assert.deepEqual(normalize(await wrapped.promises[name](file, {bigint: true})), normalize(await fs.promises[name](file, {bigint: true})));
    checks += 3;
  }
  for (const name of ['stat', 'lstat']) {
    const ordering = async owner => {
      const events = [];
      const pending = new Promise(resolve => owner[name](file, () => {events.push('callback'); resolve();}));
      process.nextTick(() => events.push('nextTick'));
      await pending;
      return events;
    };
    assert.deepEqual(await ordering(wrapped), await ordering(fs));
    checks++;
  }
  for (const target of [null, 42, {}, new URL('https://example.com/file'), 'invalid\0path']) {
    for (const name of ['statSync', 'lstatSync', 'stat', 'lstat']) {
      assert.deepEqual(outcome(() => wrapped[name](target, () => {})), outcome(() => fs[name](target, () => {})));
      checks++;
    }
  }
  for (const target of [require('node:url').pathToFileURL(file), require('node:url').pathToFileURL(missing)]) {
    for (const name of ['statSync', 'lstatSync']) {
      assert.deepEqual(outcome(() => wrapped[name](target)), outcome(() => fs[name](target)));
      checks++;
    }
    for (const name of ['stat', 'lstat']) {
      assert.deepEqual(await asyncStat(wrapped, name, target), await asyncStat(fs, name, target));
      checks++;
    }
  }
  const mixed = Array.from({length: 256}, (_, index) => asyncStat(wrapped, index % 2 ? 'stat' : 'lstat', cases[index % cases.length], {bigint: !!(index % 2)}));
  const expectedMixed = Array.from({length: 256}, (_, index) => asyncStat(fs, index % 2 ? 'stat' : 'lstat', cases[index % cases.length], {bigint: !!(index % 2)}));
  assert.deepEqual(await Promise.all(mixed), await Promise.all(expectedMixed));
  checks += mixed.length;
  const perCall = {};
  for (const name of ['statSync', 'lstatSync']) {
    splits = 0;
    wrapped[name](file);
    perCall[name] = splits;
  }
  for (const name of ['stat', 'lstat']) {
    splits = 0;
    await asyncStat(wrapped, name, file);
    perCall[name] = splits;
  }
  const session = new inspector.Session();
  session.connect();
  const post = (method, params = {}) => new Promise((resolve, reject) => session.post(method, params, (error, result) => error ? reject(error) : resolve(result)));
  await post('Profiler.enable');
  await post('Profiler.start');
  const samples = [];
  const count = Number(process.env.ZCODE_BENCH_ITERATIONS || 100000);
  for (let round = 0; round < 7; round++) {
    for (let i = 0; i < 5000; i++) wrapped.statSync(file);
    const start = performance.now();
    for (let i = 0; i < count; i++) wrapped.statSync(file);
    samples.push((performance.now() - start) * 1000 / count);
  }
  const {profile} = await post('Profiler.stop');
  session.disconnect();
  const hits = new Map();
  for (const node of profile.nodes) {
    const key = node.callFrame.functionName || '(anonymous)';
    hits.set(key, (hits.get(key) || 0) + (node.hitCount || 0));
  }
  const asyncSamples = [];
  const asyncCount = Math.min(count, 20000);
  const runAsync = count => new Promise((resolve, reject) => {
    let remaining = count;
    const next = error => {
      if (error) return reject(error);
      if (--remaining === 0) return resolve();
      wrapped.stat(file, next);
    };
    wrapped.stat(file, next);
  });
  await runAsync(1000);
  for (let round = 0; round < 7; round++) {
    const start = performance.now();
    await runAsync(asyncCount);
    asyncSamples.push((performance.now() - start) * 1000 / asyncCount);
  }
  const result = {checks, perCall, microseconds: samples, median: samples.toSorted((a, b) => a - b)[3],
    asyncMicroseconds: asyncSamples, asyncMedian: asyncSamples.toSorted((a, b) => a - b)[3],
    hotspots: [...hits].sort((a, b) => b[1] - a[1]).slice(0, 12)};
  originalFs.writeFileSync(output, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
