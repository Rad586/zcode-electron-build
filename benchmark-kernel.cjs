const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {performance} = require('node:perf_hooks');
const {app, BrowserWindow, ipcMain} = require('electron');

const output = process.env.ZCODE_BENCH_OUTPUT;
assert(output && process.env.ZCODE_BENCH_PROFILE, 'Isolated output and profile are required');
assert(!fs.existsSync(output), 'Output must be new');
app.setPath('userData', path.resolve(process.env.ZCODE_BENCH_PROFILE));
app.commandLine.appendSwitch('force_physical_gpu_for_testing');
const samples = Number(process.env.ZCODE_BENCH_SAMPLES || 5);
assert(Number.isInteger(samples) && samples >= 3);
const selected = process.env.ZCODE_BENCH_CASES?.split(',');
const scenarios = ['svg', 'style', 'layout', 'paint', 'raster', 'transfer', 'synchronization', 'ipc', 'wakeup', 'memory'];
if (selected) assert(selected.every(name => scenarios.includes(name)), 'Unknown scenario');
const watchdog = setTimeout(() => {console.error('Kernel benchmark timed out'); app.exit(1);}, 240000);

async function setup() {
  document.body.style.cssText = 'margin:0;background:white;color:black;font:14px sans-serif';
  document.body.innerHTML = '<style>.changed .cell{color:#555;background:#eee}.cell{display:inline-block;width:90px;height:22px}.grid{display:flex;flex-wrap:wrap;width:920px}.grid .cell{flex:1 0 90px}.tiles .cell{height:36px;border-radius:8px;box-shadow:0 1px 5px #888}</style><main></main><canvas width="1024" height="768"></canvas><canvas id="gl" width="512" height="512"></canvas>';
  const main = document.querySelector('main');
  const canvas = document.querySelector('canvas');
  const context = canvas.getContext('2d');
  const glCanvas = document.querySelector('#gl');
  const gl = glCanvas.getContext('webgl2', {preserveDrawingBuffer: true});
  if (!gl) throw new Error('Physical GPU WebGL2 is required');
  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
  const pixels = new Uint8Array(512 * 512 * 4);
  pixels.fill(127);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 512, 512, 0, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  const frameBuffer = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, frameBuffer);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
  if (gl.checkFramebufferStatus(gl.FRAMEBUFFER) !== gl.FRAMEBUFFER_COMPLETE) throw new Error('Incomplete framebuffer');
  const images = await Promise.all(Array.from({length: 16}, async (_, index) => {
    const image = new Image();
    const shapes = Array.from({length: 64}, (_, i) => '<rect x="' + i % 8 * 4 + '" y="' + Math.floor(i / 8) * 4 + '" width="3" height="3" fill="rgb(' + (index * 13) + ',' + (i * 3) + ',70)"/>').join('');
    image.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">' + shapes + '</svg>');
    await image.decode();
    return image;
  }));
  window.prepare = async name => {
    main.className = '';
    main.innerHTML = '';
    main.style.width = '';
    canvas.style.display = name === 'svg' || name === 'paint' ? 'block' : 'none';
    glCanvas.style.display = name === 'transfer' || name === 'synchronization' ? 'block' : 'none';
    if (['style', 'layout', 'raster'].includes(name)) {
      main.innerHTML = '<div class="cell">中文 text 123</div>'.repeat(name === 'raster' ? 3000 : 800);
      if (name === 'layout') main.className = 'grid';
      if (name === 'raster') main.className = 'tiles';
    }
    window.scrollTo(0, 0);
    await new Promise(requestAnimationFrame);
  };
  window.runCase = async name => {
    let checksum = 0;
    const start = performance.now();
    if (name === 'svg' || name === 'paint') {
      for (let i = 0; i < 3000; i++) {
        const size = name === 'paint' ? 28 + i % 3 : 32;
        context.drawImage(images[i % images.length], i % 30 * 33, Math.floor(i / 30) % 22 * 33, size, size);
      }
      checksum = context.getImageData(1, 1, 1, 1).data[3];
    } else if (name === 'style') {
      for (let i = 0; i < 100; i++) {
        main.classList.toggle('changed');
        checksum += getComputedStyle(main.lastElementChild).color.length;
      }
    } else if (name === 'layout') {
      for (let i = 0; i < 100; i++) {
        main.style.width = (900 + i % 5 * 17) + 'px';
        checksum += main.lastElementChild.offsetTop;
      }
    } else if (name === 'raster') {
      for (let i = 0; i < 60; i++) {
        window.scrollTo(0, i % 20 * 60);
        await new Promise(requestAnimationFrame);
      }
      checksum = window.scrollY;
    } else if (name === 'transfer') {
      for (let i = 0; i < 80; i++) {
        pixels[0] = i;
        gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 512, 512, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        gl.readPixels(0, 0, 512, 512, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
        if (pixels[0] !== i) throw new Error('GPU transfer changed bytes');
        checksum += pixels[0];
      }
    } else if (name === 'synchronization') {
      for (let i = 0; i < 250; i++) {
        gl.clearColor(i % 2, 0, 0, 1);
        gl.clear(gl.COLOR_BUFFER_BIT);
        gl.finish();
      }
      gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixels.subarray(0, 4));
      checksum = pixels[0];
    } else if (name === 'memory') {
      const values = [];
      for (let i = 0; i < 80000; i++) values.push({id: i, text: 'cell ' + i, child: [i, i + 1]});
      checksum = values[values.length - 1].id;
    }
    if (gl.getError() !== gl.NO_ERROR) throw new Error('WebGL error');
    return {wallMs: performance.now() - start, checksum};
  };
}

const median = values => values.toSorted((a, b) => a - b)[Math.floor(values.length / 2)];
const summary = values => {
  const mid = median(values);
  return {median: mid, relativeMad: mid ? median(values.map(value => Math.abs(value - mid))) / mid : 0};
};
async function main() {
  await app.whenReady();
  const window = new BrowserWindow({show: false, focusable: false, width: 1024, height: 768,
    webPreferences: {offscreen: true, backgroundThrottling: false, nodeIntegration: true, contextIsolation: false}});
  let paints = 0;
  window.webContents.on('paint', () => paints++);
  window.webContents.setFrameRate(60);
  ipcMain.handle('benchmark:echo', (_event, value) => value);
  try {
    await window.loadURL('data:text/html,<meta charset="utf-8">');
    await window.webContents.executeJavaScript('(' + setup.toString() + ')()');
    const debug = window.webContents.debugger;
    debug.attach('1.3');
    await debug.sendCommand('Performance.enable');
    const metric = async () => Object.fromEntries((await debug.sendCommand('Performance.getMetrics')).metrics.map(({name, value}) => [name, value]));
    const report = {electron: process.versions.electron, chromium: process.versions.chrome,
      physicalGPU: true, gpu: {status: app.getGPUFeatureStatus(), info: await app.getGPUInfo('complete')}, samples, scenarios: {}};
    assert.equal(report.gpu.status.webgl, 'enabled', 'WebGL must use hardware');
    for (const name of scenarios.filter(name => !selected || selected.includes(name))) {
      const rows = [];
      const prepare = async () => {
        await window.webContents.executeJavaScript('prepare(' + JSON.stringify(name) + ')');
        if (name === 'memory') await debug.sendCommand('HeapProfiler.collectGarbage');
      };
      const run = async () => {
        if (name === 'ipc') {
          return window.webContents.executeJavaScript(`(async () => {
            const {ipcRenderer} = require('electron');
            const payload = new Uint8Array(1024 * 1024).fill(73);
            const start = performance.now();
            for (let i = 0; i < 48; i++) {
              const result = await ipcRenderer.invoke('benchmark:echo', payload);
              if (result.length !== payload.length || result[0] !== 73 || result.at(-1) !== 73) throw new Error('IPC changed bytes');
            }
            return {wallMs: performance.now() - start, checksum: 48};
          })()`);
        }
        if (name === 'wakeup') {
          const start = performance.now();
          await new Promise(resolve => {
            let count = 0;
            const tick = () => ++count === 10000 ? resolve() : setImmediate(tick);
            setImmediate(tick);
          });
          return {wallMs: performance.now() - start, checksum: 10000};
        }
        return window.webContents.executeJavaScript('runCase(' + JSON.stringify(name) + ')');
      };
      for (let warmup = 0; warmup < 3; warmup++) {
        await prepare();
        await run();
      }
      for (let sample = 0; sample < samples; sample++) {
        await prepare();
        const before = await metric();
        const cpu = process.cpuUsage();
        const paintsBefore = paints;
        const memoryBefore = app.getAppMetrics().map(({type, memory}) => ({type, ...memory}));
        const timing = await run();
        const after = await metric();
        if (name === 'raster') assert(paints > paintsBefore, 'Raster scenario must paint');
        rows.push({...timing, paints: paints - paintsBefore, cpu: process.cpuUsage(cpu), memoryBefore,
          memoryAfter: app.getAppMetrics().map(({type, memory}) => ({type, ...memory})),
          metrics: Object.fromEntries(Object.entries(after).map(([key, value]) => [key, value - (before[key] || 0)]))});
      }
      await prepare();
      await debug.sendCommand('Tracing.start', {transferMode: 'ReturnAsStream', categories: 'devtools.timeline,blink,cc,gpu,v8'});
      await run();
      const done = new Promise(resolve => {
        const listener = (_event, method, params) => {
          if (method === 'Tracing.tracingComplete') {debug.removeListener('message', listener); resolve(params);}
        };
        debug.on('message', listener);
      });
      await debug.sendCommand('Tracing.end');
      const {stream} = await done;
      const chunks = [];
      try {
        for (;;) {
          const part = await debug.sendCommand('IO.read', {handle: stream, size: 1048576});
          chunks.push(part.base64Encoded ? Buffer.from(part.data, 'base64').toString() : part.data);
          if (part.eof) break;
        }
      } finally {await debug.sendCommand('IO.close', {handle: stream});}
      const events = JSON.parse(chunks.join('')).traceEvents;
      const totals = new Map();
      const threads = new Map();
      for (const event of events) {
        if (event.ph === 'M' && event.name === 'thread_name') threads.set(event.pid + ':' + event.tid, event.args.name);
        if (event.ph !== 'X' || !event.dur) continue;
        const key = event.pid + ':' + event.tid + ':' + event.name;
        const row = totals.get(key) || {pid: event.pid, tid: event.tid, name: event.name, ms: 0, count: 0};
        row.ms += event.dur / 1000;
        row.count++;
        totals.set(key, row);
      }
      report.scenarios[name] = {wallMs: summary(rows.map(row => row.wallMs)), rows,
        hotspots: [...totals.values()].map(row => ({...row, thread: threads.get(row.pid + ':' + row.tid)})).sort((a, b) => b.ms - a.ms).slice(0, 60)};
      fs.writeFileSync(output, JSON.stringify(report, null, 2), {flag: 'w'});
      console.log(JSON.stringify({scenario: name, ...report.scenarios[name].wallMs}));
    }
    assert.equal(window.isVisible(), false);
  } finally {
    ipcMain.removeHandler('benchmark:echo');
    window.destroy();
    clearTimeout(watchdog);
  }
  app.exit(0);
}
main().catch(error => {console.error(error); clearTimeout(watchdog); app.exit(1);});
