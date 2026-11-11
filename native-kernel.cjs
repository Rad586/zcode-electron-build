const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {Worker} = require('node:worker_threads');
const {performance} = require('node:perf_hooks');
const {app, BrowserWindow, ipcMain, MessageChannelMain} = require('electron');

const profile = process.env.ZCODE_KERNEL_PROFILE;
assert(profile, 'ZCODE_KERNEL_PROFILE is required');
app.setPath('userData', path.resolve(profile));
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-renderer-backgrounding');
const windows = new Set();
const metrics = {electron: process.versions.electron, checks: 0};
const watchdog = setTimeout(() => {console.error('Native kernel suite timed out'); app.exit(1);}, 120000);
const check = () => metrics.checks++;
async function createWindow() {
  const window = new BrowserWindow({show: false, focusable: false, webPreferences: {nodeIntegration: true, contextIsolation: false, backgroundThrottling: false}});
  windows.add(window);
  window.on('closed', () => windows.delete(window));
  await window.loadURL('data:text/html,<title>kernel fixture</title><canvas></canvas>');
  return window;
}
async function main() {
  await app.whenReady();
  const start = performance.now();
  const window = await createWindow();
  metrics.windowReadyMs = performance.now() - start;
  ipcMain.handle('kernel:echo', (_event, value) => value);
  const result = await window.webContents.executeJavaScript(`(async () => {
    const assert = require('node:assert/strict');
    const {ipcRenderer} = require('electron');
    let checks = 0;
    const samples = [];
    const cycle = {label: 'cycle'}; cycle.self = cycle;
    const values = [null, undefined, false, 0, -1, 1.25, 2n ** 80n, '中文😀'.repeat(2000), new Date(12345), /abc/gi, new Map([['k', 42]]), new Set([1, 2]), cycle];
    for (const value of values) {assert.deepEqual(await ipcRenderer.invoke('kernel:echo', value), value); checks++;}
    for (const size of [0, 1, 65500, 65536, 65537, 131072, 1048576, 4194304]) {
      const buffer = new Uint8Array(size + 32);
      for (let i = 0; i < buffer.length; i++) buffer[i] = i % 251;
      const value = buffer.subarray(11, 11 + size);
      const received = await ipcRenderer.invoke('kernel:echo', value);
      assert.deepEqual(received, value); checks++;
      const start = performance.now();
      for (let i = 0; i < 8; i++) await ipcRenderer.invoke('kernel:echo', value);
      samples.push({bytes: size, roundTripMs: (performance.now() - start) / 8});
    }
    let rejected = false;
    try { await ipcRenderer.invoke('kernel:echo', () => 1); } catch { rejected = true; }
    assert.equal(rejected, true); checks++;
    const results = await Promise.all(Array.from({length: 256}, (_, id) => ipcRenderer.invoke('kernel:echo', {id, text: '界'.repeat(256)})));
    results.forEach((value, id) => assert.equal(value.id, id)); checks++;
    return {checks, samples};
  })().catch(error => ({failure: String(error.stack)}))`);
  assert.equal(result.failure, undefined, result.failure);
  metrics.checks += result.checks;
  metrics.ipc = result.samples;
  await window.webContents.executeJavaScript(`require('electron').ipcRenderer.on('kernel:port-next', event => event.ports[0].postMessage({ok:true})); undefined`);
  const nextChannel = new MessageChannelMain();
  nextChannel.port1.start();
  const nextPortResult = new Promise(resolve => nextChannel.port1.once('message', ({data}) => resolve(data)));
  window.webContents.postMessage('kernel:port-next', null, [nextChannel.port2]);
  assert.deepEqual(await nextPortResult, {ok: true});
  nextChannel.port1.close();
  check();
  const channels = Array.from({length: 64}, () => new MessageChannelMain());
  try {
    const received = channels.map(({port1, port2}) => {
      port1.start();
      const reply = new Promise(resolve => port1.once('message', ({data}) => resolve(data)));
      window.webContents.postMessage('kernel:port-next', null, [port2]);
      return reply;
    });
    for (const reply of await Promise.all(received)) {
      assert.deepEqual(reply, {ok: true});
      check();
    }
  } finally {
    for (const {port1} of channels) port1.close();
  }
  const immediateStart = performance.now();
  await new Promise(resolve => {
    let count = 0;
    const step = () => ++count === 20000 ? resolve() : setImmediate(step);
    setImmediate(step);
  });
  metrics.immediateMs = performance.now() - immediateStart;
  check();
  let ticks = 0;
  const timer = setInterval(() => ticks++, 2);
  const socketBytes = await new Promise((resolve, reject) => {
    const server = net.createServer(socket => socket.pipe(socket));
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const client = net.connect(server.address().port, '127.0.0.1');
      let received = 0;
      client.on('error', reject);
      client.on('connect', () => client.end(Buffer.alloc(2 * 1024 * 1024, 37)));
      client.on('data', data => {received += data.length; assert(data.every(byte => byte === 37));});
      client.on('end', () => server.close(() => resolve(received)));
    });
  });
  clearInterval(timer);
  assert.equal(socketBytes, 2 * 1024 * 1024);
  metrics.timerTicksDuringIo = ticks;
  check();
  for (let round = 0; round < 4; round++) {
    const worker = new Worker(`const {parentPort} = require('node:worker_threads'); let n=0; const tick=()=>++n===2000?parentPort.postMessage(n):setImmediate(tick); tick();`, {eval: true});
    assert.equal(await new Promise((resolve, reject) => {worker.once('message', resolve); worker.once('error', reject);}), 2000);
    await worker.terminate();
    check();
  }
  for (let round = 0; round < 20; round++) {
    await window.loadURL('data:text/html,<title>navigation ' + round + '</title>');
    assert.equal(await window.webContents.executeJavaScript(`new Promise(resolve => setTimeout(() => resolve(42), 2))`), 42);
    const child = await createWindow();
    assert.equal(await child.webContents.executeJavaScript(`require('electron').ipcRenderer.invoke('kernel:echo', 'alive')`), 'alive');
    child.destroy();
    check();
  }
  assert.equal(windows.size, 1);
  assert.equal(BrowserWindow.getAllWindows().length, 1);
  check();
  const idleStart = process.cpuUsage();
  const idleWall = performance.now();
  await new Promise(resolve => setTimeout(resolve, 1000));
  metrics.idle = {wallMs: performance.now() - idleWall, cpu: process.cpuUsage(idleStart)};
  ipcMain.removeHandler('kernel:echo');
  for (const owned of windows) owned.destroy();
  clearTimeout(watchdog);
  if (process.env.ZCODE_KERNEL_OUTPUT) fs.writeFileSync(process.env.ZCODE_KERNEL_OUTPUT, JSON.stringify(metrics, null, 2));
  console.log(JSON.stringify(metrics));
  app.quit();
}
main().catch(error => {console.error(error); clearTimeout(watchdog); app.exit(1);});
