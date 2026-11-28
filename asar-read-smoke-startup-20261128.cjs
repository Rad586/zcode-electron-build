'use strict';

// ELECTRON_RUN_AS_NODE=1 electron.exe SCRIPT baseline|patched FIXTURE_ASAR OUTPUT_JSON
const assert = require('node:assert/strict');
const fs = require('node:fs');
const original = require('original-fs');
const { Session } = require('node:inspector');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

async function main() {
  const [mode, fixture, output] = process.argv.slice(2);
  assert((mode === 'baseline' || mode === 'patched') && fixture && output,
    'Expected baseline|patched FIXTURE_ASAR OUTPUT_JSON');
  assert(process.versions.electron && process.env.ELECTRON_RUN_AS_NODE === '1');
  const archive = path.resolve(fixture);
  const files = [path.join(archive, 'file1'), path.join(archive, 'dir1', 'file1'), path.join(archive, 'link1')];
  const readsPerBatch = 8;
  let checks = 0;
  const session = new Session();
  session.connect();
  const post = (method, params) => new Promise((resolve, reject) =>
    session.post(method, params, (error, result) => error ? reject(error) : resolve(result)));
  const stockAdapterCalls = [];
  try {
    await post('Profiler.enable');
    await post('Profiler.startPreciseCoverage', { callCount: true, detailed: false });
    await post('Profiler.takePreciseCoverage');
    for (let batch = 0; batch < 2; batch++) {
      for (let i = 0; i < readsPerBatch; i++) {
        const file = files[i % files.length];
        const input = [file, Buffer.from(file), pathToFileURL(file)][(i + batch) % 3];
        const contents = await fs.promises.readFile(input, 'utf8');
        assert.equal(contents.trim(), 'file1');
        checks++;
      }
      const { result } = await post('Profiler.takePreciseCoverage');
      const matches = result.filter(script => script.url === 'node:internal/util')
        .flatMap(script => script.functions.filter(fn => fn.functionName === 'promisify'));
      assert(matches.length <= 1, 'Ambiguous stock adapter coverage');
      stockAdapterCalls.push(matches[0]?.ranges[0].count ?? 0);
    }
    await post('Profiler.stopPreciseCoverage');
  } finally { session.disconnect(); }
  assert.deepEqual(stockAdapterCalls, mode === 'baseline' ? [readsPerBatch, readsPerBatch] : [1, 0]);
  checks++;
  const bytes = await original.promises.readFile(archive);
  process.noAsar = true;
  try { assert.deepEqual(await fs.promises.readFile(archive), bytes); checks++; }
  finally { delete process.noAsar; }
  const missing = path.join(archive, 'missing');
  await assert.rejects(fs.promises.readFile(missing), { code: 'ENOENT' });
  checks++;
  assert.equal(fs.readFileSync(files[0], 'utf8').trim(), 'file1');
  checks++;
  const callbackRead = await new Promise((resolve, reject) => {
    fs.readFile(files[0], 'utf8', (error, data) => error ? reject(error) : resolve(data));
  });
  assert.equal(callbackRead.trim(), 'file1');
  checks++;
  assert.deepEqual(await fs.promises.readFile(__filename), original.readFileSync(__filename));
  checks++;
  original.writeFileSync(output, JSON.stringify({ schema: 1, mode, electron: process.versions.electron,
    chrome: process.versions.chrome, checks, readsPerBatch, stockAdapterCalls }, null, 2) + '\n', { flag: 'wx' });
}

main().catch(error => { console.error(error); process.exitCode = 1; });
