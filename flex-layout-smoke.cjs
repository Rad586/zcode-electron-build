const assert = require('node:assert/strict');
const path = require('node:path');
const {app, BrowserWindow} = require('electron');

assert(process.env.ZCODE_FLEX_PROFILE, 'An isolated flex profile is required');
app.setPath('userData', path.resolve(process.env.ZCODE_FLEX_PROFILE));
const timeout = setTimeout(() => app.exit(1), 30000);
app.whenReady().then(async () => {
  const window = new BrowserWindow({show: false});
  try {
    await window.loadURL('data:text/html,<meta charset="utf-8">');
    const results = await window.webContents.executeJavaScript(`(() => {
      document.body.innerHTML = \`<style>
        .row { display: flex; flex-wrap: wrap; width: 100px; }
        .row > div { flex: 1 0 40px; width: 40px; height: 20px; }
        .column { display: flex; flex-direction: column; align-items: start; width: 100px; }
        .column > table { flex: 0 0 32px; width: 60px; border-spacing: 0; }
      </style>
      <section class="row"><div></div><div></div><div></div></section>
      <section class="column">
        <div id="ratio" style="width:30px;aspect-ratio:2"></div>
        <div id="intrinsic"><div style="width:30px;height:14px"></div></div>
        <div id="orthogonal" style="writing-mode:vertical-rl;flex:0 0 17px;width:23px"></div>
        <table id="table"><caption style="height:10px"></caption><tbody><tr><td></td></tr></tbody></table>
      </section>\`;
      const row = document.querySelector('.row');
      const rows = [100, 130, 100].map(width => {
        row.style.width = width + 'px';
        return [...row.children].map(child => [child.offsetWidth, child.offsetTop - row.offsetTop]);
      });
      const boxes = ['ratio', 'intrinsic', 'orthogonal', 'table'].map(id => {
        const node = document.getElementById(id);
        return [node.offsetWidth, node.offsetHeight];
      });
      return {rows, boxes};
    })()`);
    assert.deepEqual(results, {
      rows: [[[50, 0], [50, 0], [100, 20]], [[43, 0], [43, 0], [43, 0]],
        [[50, 0], [50, 0], [100, 20]]],
      boxes: [[30, 15], [30, 14], [23, 17], [60, 42]],
    });
    assert.equal(window.isVisible(), false);
    console.log(JSON.stringify({electron: process.versions.electron, results}));
  } finally {
    window.destroy();
    clearTimeout(timeout);
  }
  app.exit(0);
}).catch(error => {console.error(error); app.exit(1);});
