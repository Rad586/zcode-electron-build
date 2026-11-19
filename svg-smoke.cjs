const assert = require('node:assert/strict');
const path = require('node:path');
const {app, BrowserWindow} = require('electron');

app.setPath('userData', path.resolve(process.env.ZCODE_SVG_PROFILE));
const timeout = setTimeout(() => app.exit(1), 30000);
app.whenReady().then(async () => {
  const window = new BrowserWindow({show: false, webPreferences: {backgroundThrottling: false}});
  try {
    await window.loadURL('data:text/html,<canvas width="100" height="100"></canvas>');
    const results = await window.webContents.executeJavaScript(`(async () => {
      const canvas = document.querySelector('canvas'), ctx = canvas.getContext('2d');
      const load = async (body, fragment = '') => {
        const image = new Image();
        image.src = URL.createObjectURL(new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">' + body + '</svg>'], {type: 'image/svg+xml'})) + fragment;
        await image.decode();
        document.body.append(image);
        return image;
      };
      const pixel = (image, width = 100, x = 25, y = 25) => {
        ctx.clearRect(0, 0, 100, 100);
        ctx.drawImage(image, 0, 0, width, width);
        return Array.from(ctx.getImageData(x, y, 1, 1).data);
      };
      const staticImage = await load('<rect width="100%" height="100%" fill="red"/>');
      const first = pixel(staticImage);
      let repeated = true;
      for (let i = 0; i < 100; i++) repeated &&= String(pixel(staticImage)) === String(first);
      const small = pixel(staticImage, 20, 10, 10), large = pixel(staticImage, 100, 90, 90);
      ctx.clearRect(0, 0, 100, 100);
      ctx.drawImage(staticImage, 0, 0, 50, 50, 0, 0, 100, 100);
      const cropped = Array.from(ctx.getImageData(90, 90, 1, 1).data);
      ctx.clearRect(0, 0, 100, 100);
      ctx.drawImage(staticImage, 50, 50, 50, 50, 0, 0, 100, 100);
      const otherCrop = Array.from(ctx.getImageData(90, 90, 1, 1).data);
      const views = '<view id="right" viewBox="50 0 50 100"/><rect width="50" height="100" fill="red"/><rect x="50" width="50" height="100" fill="blue"/>';
      const ordinary = await load(views), fragment = await load(views, '#right');
      const ordinaryPixel = pixel(ordinary), fragmentPixel = pixel(fragment);
      const crop = x => {
        ctx.clearRect(0, 0, 100, 100);
        ctx.drawImage(ordinary, x, 0, 50, 100, 0, 0, 100, 100);
        return Array.from(ctx.getImageData(75, 50, 1, 1).data);
      };
      const cropLeft = crop(0), cropRight = crop(50), cropLeftAgain = crop(0);
      const animated = await load('<rect width="100" height="100" fill="red"><animate attributeName="fill" values="red;blue" dur="0.1s" fill="freeze"/></rect>');
      const animationStart = pixel(animated);
      let animationEnd;
      for (let i = 0; i < 60; i++) {
        await new Promise(requestAnimationFrame);
        animationEnd = pixel(animated);
        if (animationEnd[2] > animationEnd[0]) break;
      }
      return {first,repeated,small,large,cropped,otherCrop,ordinaryPixel,fragmentPixel,cropLeft,cropRight,cropLeftAgain,animationStart,animationEnd};
    })()`);
    console.log(JSON.stringify({electron: process.versions.electron, results}));
    assert.deepEqual(results.first, [255, 0, 0, 255]);
    assert.equal(results.repeated, true);
    assert.deepEqual(results.small, results.first);
    assert.deepEqual(results.large, results.first);
    assert.deepEqual(results.cropped, results.first);
    assert.deepEqual(results.otherCrop, results.first);
    assert.deepEqual(results.cropLeft, results.first);
    assert.deepEqual(results.cropRight, [0, 0, 255, 255]);
    assert.deepEqual(results.cropLeftAgain, results.first);
    assert.deepEqual(results.ordinaryPixel, results.first);
    assert.deepEqual(results.fragmentPixel, [0, 0, 255, 255]);
    assert(results.animationEnd[2] > results.animationEnd[0], 'SVG animation must advance toward blue');
    assert.notDeepEqual(results.animationStart, results.animationEnd);
    assert.equal(window.isVisible(), false);
  } finally {
    window.destroy();
    clearTimeout(timeout);
  }
  app.exit(0);
}).catch(error => {console.error(error); app.exit(1);});
