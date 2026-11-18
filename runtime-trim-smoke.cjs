const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const {app, BrowserWindow, Notification} = require('electron');

assert(process.env.ZCODE_TRIM_PROFILE, 'ZCODE_TRIM_PROFILE is required');
app.setPath('userData', path.resolve(process.env.ZCODE_TRIM_PROFILE));
app.commandLine.appendSwitch('force_physical_gpu_for_testing');
const watchdog = setTimeout(() => {console.error('Runtime trim suite timed out'); app.exit(1);}, 90000);
const fixtures = process.env.ZCODE_TRIM_FIXTURES;
assert(fixtures, 'ZCODE_TRIM_FIXTURES is required');
const results = {};
const windows = new Set();
const baseline = process.env.ZCODE_TRIM_BASELINE === '1';
const pdfStream = '1 0 0 rg 0 0 300 300 re f';
const objects = [
  '<< /Type /Catalog /Pages 2 0 R >>',
  '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
  '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << >> /Contents 4 0 R >>',
  `<< /Length ${Buffer.byteLength(pdfStream)} >>\nstream\n${pdfStream}\nendstream`,
];
let pdf = '%PDF-1.4\n';
const offsets = [0];
objects.forEach((object, index) => {offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;});
const xref = Buffer.byteLength(pdf);
pdf += `xref\n0 5\n0000000000 65535 f \n${offsets.slice(1).map(offset => String(offset).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
const assets = new Map([
  ['/test.pdf', ['application/pdf', Buffer.from(pdf)]],
  ['/tone.wav', ['audio/wav', fs.readFileSync(path.join(fixtures, 'assets/tone.wav'))]],
  ['/cat.mp4', ['video/mp4', fs.readFileSync(path.join(fixtures, 'cat-spin.mp4'))]],
]);
const server = http.createServer((request, response) => {
  const [type, data] = assets.get(request.url) || ['text/html', Buffer.from('<canvas></canvas><math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>')];
  response.writeHead(200, {'Content-Type': type, 'Content-Length': data.length});
  response.end(data);
});
async function createWindow(url) {
  const window = new BrowserWindow({show: false, focusable: false, width: 800, height: 700,
    webPreferences: {backgroundThrottling: false, plugins: true}});
  windows.add(window);
  window.once('closed', () => windows.delete(window));
  await window.loadURL(url);
  return window;
}
async function main() {
  await app.whenReady();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const window = await createWindow(origin);
  results.web = await window.webContents.executeJavaScript(`(async () => {
    const disabled = {
      gamepad: typeof navigator.getGamepads === 'undefined',
      serviceWorker: !('serviceWorker' in navigator),
      encryptedMedia: !('requestMediaKeySystemAccess' in navigator),
      mediaRecorder: typeof MediaRecorder === 'undefined',
      peerConnection: typeof RTCPeerConnection === 'undefined' && typeof webkitRTCPeerConnection === 'undefined',
      mediaCapture: !('mediaDevices' in navigator) && !('getUserMedia' in navigator) && !('webkitGetUserMedia' in navigator),
      speech: typeof SpeechRecognition === 'undefined' && typeof webkitSpeechRecognition === 'undefined' && typeof speechSynthesis === 'undefined',
      bluetooth: !('bluetooth' in navigator), usb: !('usb' in navigator), hid: !('hid' in navigator), serial: !('serial' in navigator),
      xr: !('xr' in navigator), push: typeof PushManager === 'undefined',
      payment: typeof PaymentRequest === 'undefined', xslt: typeof XSLTProcessor === 'undefined',
    };
    const gl = document.querySelector('canvas').getContext('webgl2');
    if (!gl) throw new Error('WebGL2 unavailable');
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    const renderer = gl.getParameter(debug.UNMASKED_RENDERER_WEBGL);
    gl.clearColor(0.25, 0.5, 0.75, 1); gl.clear(gl.COLOR_BUFFER_BIT);
    const pixel = new Uint8Array(4); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
    const decoded = {};
    for (const [tag, source] of [['audio', '/tone.wav'], ['video', '/cat.mp4']]) {
      const media = document.createElement(tag); media.muted = true; media.src = source;
      document.body.append(media);
      await new Promise((resolve, reject) => {media.onloadeddata = resolve; media.onerror = () => reject(new Error(tag + ' decode failed: ' + media.error?.message));});
      await media.play();
      if (tag === 'video') await new Promise(resolve => media.requestVideoFrameCallback(resolve));
      else await new Promise(resolve => setTimeout(resolve, 100));
      decoded[tag] = {time: media.currentTime, readyState: media.readyState, width: media.videoWidth || 0};
      media.pause(); media.remove();
    }
    const context = new OfflineAudioContext(1, 2048, 48000);
    const oscillator = context.createOscillator(); oscillator.connect(context.destination); oscillator.start();
    const audio = await context.startRendering();
    const locales = ['en-US', 'zh-CN', 'zh-TW'];
    return {disabled, renderer, pixel: Array.from(pixel), decoded,
      audioEnergy: audio.getChannelData(0).reduce((sum, value) => sum + value * value, 0),
      locales: locales.map(locale => ({locale, date: new Intl.DateTimeFormat(locale, {dateStyle:'full',timeZone:'Asia/Shanghai'}).format(0), number: new Intl.NumberFormat(locale).format(1234.5)})),
      webauthn: typeof PublicKeyCredential === 'function' && typeof navigator.credentials.get === 'function',
      notification: typeof Notification === 'function',
      mathml: getComputedStyle(document.querySelector('math')).mathStyle,
    };
  })()`);
  if (!baseline) for (const [name, disabled] of Object.entries(results.web.disabled)) assert.equal(disabled, true, name + ' remains exposed');
  assert.match(results.web.renderer, /D3D11/);
  results.web.pixel.slice(0, 3).forEach((value, index) => assert(Math.abs(value - [64, 128, 191][index]) <= 1));
  assert(results.web.audioEnergy > 100);
  assert(results.web.decoded.video.width > 0);
  assert(results.web.decoded.audio.readyState >= 2);
  assert.equal(results.web.webauthn, true);
  assert.equal(results.web.notification, true);
  assert.equal(results.web.mathml, 'compact');
  assert.equal(Notification.isSupported(), true);
  window.webContents.debugger.attach('1.3');
  await window.webContents.debugger.sendCommand('Performance.enable');
  results.cdp = await window.webContents.debugger.sendCommand('Performance.getMetrics');
  assert(results.cdp.metrics.some(metric => metric.name === 'JSHeapUsedSize'));
  await window.webContents.debugger.sendCommand('Tracing.start', {categories: 'devtools.timeline', transferMode: 'ReturnAsStream'});
  const traceDone = new Promise(resolve => window.webContents.debugger.on('message', (_event, method, parameters) => {
    if (method === 'Tracing.tracingComplete') resolve(parameters);
  }));
  await window.webContents.debugger.sendCommand('Runtime.evaluate', {expression:'document.body.offsetHeight'});
  await window.webContents.debugger.sendCommand('Tracing.end');
  const trace = await traceDone;
  const chunk = await window.webContents.debugger.sendCommand('IO.read', {handle: trace.stream});
  assert(chunk.data.includes('traceEvents'));
  await window.webContents.debugger.sendCommand('IO.close', {handle: trace.stream});
  window.webContents.debugger.detach();
  results.gpu = {status: app.getGPUFeatureStatus(), info: await app.getGPUInfo('complete')};
  const viewer = await createWindow(origin + '/test.pdf');
  let redPixels = 0;
  for (let attempt = 0; attempt < 60 && redPixels < 10000; attempt++) {
    const bitmap = (await viewer.webContents.capturePage({x:0, y:0, width:800, height:700}, {stayHidden: true, stayAwake: true})).toBitmap();
    redPixels = 0;
    for (let index = 0; index < bitmap.length; index += 4) if (bitmap[index] < 30 && bitmap[index + 1] < 30 && bitmap[index + 2] > 220) redPixels++;
    if (redPixels < 10000) await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(redPixels >= 10000, 'Built-in PDF viewer did not render the red page');
  results.pdfRedPixels = redPixels;
  assert([...windows].every(owned => !owned.isVisible()));
  if (process.env.ZCODE_TRIM_OUTPUT) fs.writeFileSync(process.env.ZCODE_TRIM_OUTPUT, JSON.stringify(results, null, 2), {flag:'wx'});
  console.log(JSON.stringify(results));
  for (const owned of windows) owned.destroy();
  server.close();
  clearTimeout(watchdog);
  app.quit();
}
main().catch(error => {console.error(error); clearTimeout(watchdog); app.exit(1);});
