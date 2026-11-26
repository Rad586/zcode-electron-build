const assert = require('node:assert/strict');
const path = require('node:path');
const {app, BrowserWindow} = require('electron');

assert(process.env.ZCODE_CURRENTCOLOR_PROFILE, 'ZCODE_CURRENTCOLOR_PROFILE is required');
app.setPath('userData', path.resolve(process.env.ZCODE_CURRENTCOLOR_PROFILE));
app.commandLine.appendSwitch('disable-renderer-backgrounding');
const timeout = setTimeout(() => app.exit(1), 30000);
app.whenReady().then(async () => {
  const window = new BrowserWindow({show: false, focusable: false, width: 800, height: 600,
    webPreferences: {offscreen: true, backgroundThrottling: false}});
  try {
    await window.loadURL('data:text/html,<style>body{margin:0;color:red}.tile{position:absolute;width:40px;height:40px}.inset{position:absolute;left:8px;top:8px;width:24px;height:24px}</style>');
    const cases = await window.webContents.executeJavaScript(`(() => {
      const cases = [
        ['background', '<div style="width:40px;height:40px;background:currentColor"></div>', 20, 20],
        ['border', '<div style="width:24px;height:24px;border:8px solid currentColor"></div>', 4, 20],
        ['outline', '<div class="inset" style="outline:8px solid currentColor"></div>', 4, 20],
        ['box-shadow', '<div class="inset" style="box-shadow:0 0 0 8px currentColor"></div>', 4, 20],
        ['drop-shadow', '<div style="width:16px;height:40px;background:white;filter:drop-shadow(24px 0 0 currentColor)"></div>', 30, 20],
        ['svg-fill', '<svg width="40" height="40"><rect width="40" height="40" fill="currentColor"/></svg>', 20, 20],
        ['svg-stroke', '<svg width="40" height="40"><path d="M0 20H40" stroke="currentColor" stroke-width="20"/></svg>', 20, 20],
        ['svg-stop', '<svg width="40" height="40"><defs><linearGradient id="g"><stop stop-color="currentColor"/><stop offset="1" stop-color="currentColor"/></linearGradient></defs><rect width="40" height="40" fill="url(#g)"/></svg>', 20, 20],
        ['svg-flood', '<svg width="40" height="40"><defs><filter id="f"><feFlood flood-color="currentColor"/></filter></defs><rect width="40" height="40" filter="url(#f)"/></svg>', 20, 20],
        ['border-gradient', '<div style="width:24px;height:24px;border:8px solid;border-image:linear-gradient(currentColor,currentColor) 1"></div>', 4, 20],
        ['background-gradient', '<div style="width:40px;height:40px;background:linear-gradient(currentColor,currentColor)"></div>', 20, 20],
        ['explicit-background', '<div style="width:40px;height:40px;background:rgb(0,128,0)"></div>', 20, 20, [0,128,0]],
        ['transparent-border', '<div style="width:40px;height:40px;border:0 solid currentColor;background:rgb(0,128,0)"></div>', 20, 20, [0,128,0]],
        ['border-top', '<div style="width:40px;height:32px;border-top:8px solid currentColor"></div>', 20, 4],
        ['border-right', '<div style="width:32px;height:40px;border-right:8px solid currentColor"></div>', 36, 20],
        ['border-bottom', '<div style="width:40px;height:32px;border-bottom:8px solid currentColor"></div>', 20, 36],
        ['outline-none', '<div style="width:40px;height:40px;outline:0 solid currentColor;background:rgb(0,128,0)"></div>', 20, 20, [0,128,0]],
        ['svg-fill-fallback', '<svg width="40" height="40"><rect width="40" height="40" fill="url(#missing-fill) currentColor"/></svg>', 20, 20],
        ['svg-stroke-fallback', '<svg width="40" height="40"><path d="M0 20H40" stroke="url(#missing-stroke) currentColor" stroke-width="20"/></svg>', 20, 20],
        ['svg-stroke-none', '<svg width="40" height="40"><rect width="40" height="40" fill="rgb(0,128,0)" stroke="none"/></svg>', 20, 20, [0,128,0]],
        ['background-layers', '<div style="width:40px;height:40px;background-image:linear-gradient(transparent,transparent),linear-gradient(currentColor,currentColor)"></div>', 20, 20],
      ];
      cases.forEach(([name, html], i) => {
        const tile = document.createElement('div');
        tile.className = 'tile';
        tile.style.left = (i % 8 * 60) + 'px';
        tile.style.top = (Math.floor(i / 8) * 60) + 'px';
        tile.innerHTML = html;
        document.body.append(tile);
      });
      return cases.map(([name, html, x, y, fixed], i) => ({name, x: i % 8 * 60 + x,
        y: Math.floor(i / 8) * 60 + y, fixed}));
    })()`);
    const captureHeight = Math.ceil(cases.length / 8) * 60;
    let checks = 0;
    for (const [css, rgb] of [['red', [255,0,0]], ['blue', [0,0,255]], ['red', [255,0,0]]]) {
      await window.webContents.executeJavaScript(`document.body.style.color = ${JSON.stringify(css)}; new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))`);
      const image = await window.webContents.capturePage({x: 0, y: 0, width: 480, height: captureHeight});
      const {width, height} = image.getSize();
      const pixels = image.toBitmap();
      // capturePage uses physical pixels on scaled displays.
      for (const test of cases) {
        const x = Math.floor(test.x * width / 480), y = Math.floor(test.y * height / captureHeight);
        const offset = (y * width + x) * 4;
        const actual = [pixels[offset + 2], pixels[offset + 1], pixels[offset]];
        assert.deepEqual(actual, test.fixed || rgb, test.name + ' after ' + css);
        checks++;
      }
    }
    assert.equal(window.isVisible(), false);
    console.log(JSON.stringify({electron: process.versions.electron, checks}));
  } finally {
    window.destroy();
    clearTimeout(timeout);
  }
  app.exit(0);
}).catch(error => {console.error(error); app.exit(1);});
