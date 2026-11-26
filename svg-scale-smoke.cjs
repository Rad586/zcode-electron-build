const assert = require('node:assert/strict');
const path = require('node:path');
const {app, BrowserWindow} = require('electron');

assert(process.env.ZCODE_SVG_PROFILE, 'An isolated SVG profile is required');
app.setPath('userData', path.resolve(process.env.ZCODE_SVG_PROFILE));
const timeout = setTimeout(() => app.exit(1), 30000);
app.whenReady().then(async () => {
  const window = new BrowserWindow({show: false, webPreferences: {backgroundThrottling: false}});
  try {
    await window.loadURL('data:text/html,<canvas width="200" height="200"></canvas>');
    const results = await window.webContents.executeJavaScript(`(async () => {
      const ctx = document.querySelector('canvas').getContext('2d');
      const load = async body => {
        const url = URL.createObjectURL(new Blob([
          '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">' + body + '</svg>',
        ], {type: 'image/svg+xml'}));
        try {
          const image = new Image();
          image.src = url;
          await image.decode();
          return image;
        } finally {
          URL.revokeObjectURL(url);
        }
      };
      const images = {
        resources: await load('<defs><linearGradient id="paint"><stop stop-color="red"/><stop offset="1" stop-color="red"/></linearGradient><clipPath id="clip"><rect x="25" y="25" width="50" height="50"/></clipPath></defs><rect width="100" height="100" fill="url(#paint)" clip-path="url(#clip)"/>'),
        stroke: await load('<defs><path id="line" d="M20 50H80" stroke="blue" stroke-width="8" vector-effect="non-scaling-stroke"/></defs><use href="#line"/>'),
      };
      const sizes = [[100, 100], [180, 60], [60, 180], [180, 60], [100, 100]];
      const draw = (image, width, height) => {
        ctx.clearRect(0, 0, 200, 200);
        ctx.drawImage(image, 0, 0, width, height);
      };
      const pixel = (x, y) => Array.from(ctx.getImageData(x, y, 1, 1).data);
      return sizes.map(([width, height]) => {
        draw(images.resources, width, height);
        const pixels = [pixel(width / 2, height / 2), pixel(width / 10, height / 2)];
        draw(images.stroke, width, height);
        const column = ctx.getImageData(width / 2, 0, 1, height).data;
        const painted = [];
        for (let y = 0; y < height; y++) {
          if (column[4 * y + 3] > 128) painted.push(y - height / 2);
        }
        return {width, height, pixels, painted};
      });
    })()`);
    assert.equal(results.length, 5);
    for (const {pixels, painted} of results) {
      assert.deepEqual(pixels, [[255, 0, 0, 255], [0, 0, 0, 0]]);
      assert.deepEqual(painted, [-4, -3, -2, -1, 0, 1, 2, 3]);
    }
    assert.equal(window.isVisible(), false);
    console.log(JSON.stringify({electron: process.versions.electron, results}));
  } finally {
    window.destroy();
    clearTimeout(timeout);
  }
  app.exit(0);
}).catch(error => {console.error(error); app.exit(1);});
