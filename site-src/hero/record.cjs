// Step the hero stage frame by frame and save PNGs. Called by record.py.
//
//   node site-src/hero/record.cjs STAGE.html OUT_DIR --fps 30 [--scale 1.2] [--at 1.0,4.6]
//
// Frames are exact: each one calls the stage's seek(t) and screenshots, so the
// result does not depend on how fast this machine renders (no recordVideo jitter).
// --at writes one still per listed second instead of a whole loop.
// Needs Playwright with Chromium: npm i playwright, or set PLAYWRIGHT to its folder.
const path = require('path');
const { chromium } = require(process.env.PLAYWRIGHT || 'playwright');

function arg(name, dflt) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 ? process.argv[i + 1] : dflt;
}

process.on('unhandledRejection', (e) => { console.error(String(e)); process.exit(1); });

(async () => {
  const [stage, out] = process.argv.slice(2);
  const fps = Number(arg('fps', '30'));
  const scale = Number(arg('scale', '1'));
  const at = arg('at', '');
  const browser = await chromium.launch({ args: ['--disable-features=MacAppCodeSignClone'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: scale });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('file://' + path.resolve(stage) + '?record=1' + (process.env.STAGE_QUERY || ''));
  // A stage that cannot measure itself (say, no Copy button for the fix) rejects
  // heroReady; fail loudly rather than hang.
  await page.evaluate(() => Promise.race([window.heroReady, new Promise((_, rej) =>
    setTimeout(() => rej(new Error('stage not ready after 20 s')), 20000))]));
  const duration = await page.evaluate(() => DURATION);
  const times = at ? at.split(',').map(Number)
    : Array.from({ length: Math.round(duration * fps) }, (_, i) => i / fps);
  for (let i = 0; i < times.length; i++) {
    await page.evaluate((t) => window.seek(t), times[i]);
    const name = at ? `still-${String(times[i].toFixed(2)).padStart(5, '0')}s.png`
      : `f${String(i).padStart(4, '0')}.png`;
    await page.screenshot({ path: path.join(out, name) });
  }
  await browser.close();
  if (errors.length) { console.error(errors.join('\n')); process.exit(1); }
  console.log(`${times.length} frames -> ${out}`);
})();
