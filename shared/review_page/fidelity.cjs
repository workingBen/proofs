// Fidelity: does a copy of a page (Refine's snapshot "base") look like the page it was taken from?
// Used by the capture's tests on its --snapshot output and by smoke.cjs on a Refine base with every
// layer off, against the before capture at 1280 and 390 (spec §2, "Fidelity check").
//
// compareShots(pngA, pngB, { signatures: [sigA, sigB] }?) resolves to { pixelRatio, signature }:
//   pngA, pngB  file paths or PNG bytes (8-bit RGB or RGBA, as Chrome writes; both at the same
//               device scale, which is the caller's job).
//   pixelRatio  0 to 1: the share of pixels whose R, G or B differ by more than CHANNEL_TOLERANCE,
//               over the union of the two images (the wider width times the taller height). A
//               pixel only one image has counts as different, so a copy 40 px taller than the page
//               is 40 rows' worth worse, never better. Alpha is ignored: screenshots are opaque.
//   signature   0 to 1, signature.cjs's layout similarity of the two sides' layout signatures
//               (layoutSignature or signatureFromSection output) when the caller passes them as
//               `signatures`; null when it has none. A PNG alone carries no boxes to compare, so
//               null means "not measured", not "different".
// A copy passes when pixelRatio <= FIDELITY.pixelRatio and signature is null or
// >= FIDELITY.signature. smoke.cjs passes no signatures (a before shot is a PNG), so its
// fidelity is the pixel measure alone.
//
// Also: renderBase (a base shot as the capture shoots a page, SHOT_VIEWPORTS), shotNames (the
// before shots beside a snapshot), and comparePicks with MISSED_PICKS, match.cjs's measure of a
// built page against the preview of its picks (spec §7).

const path = require('path');
const { similarity } = require('./signature.cjs');
// The same PNG reader the capture uses (png.cjs), so both read a shot the same way.
const { decodePng } = require('./png.cjs');

// Per-channel tolerance, out of 255. Two renders of the same DOM are not byte-identical: text
// antialiasing, gradient dithering and image resampling move edge pixels by a few levels. 16
// (about 6%) absorbs that jitter, while anything a reader would see (a lost font, a missing
// image, a block shifted by a pixel) moves its pixels far more than 16 at every edge it touches.
const CHANNEL_TOLERANCE = 16;

// Thresholds, each with its reason.
//   pixelRatio 0.01: at 1280 x 800 that is about 10,000 px, less than one line of 16 px body text
//     set in the wrong font, so a lost web font, image or stylesheet fails, while a faithful copy
//     (the capture fixture's snapshot measures 0 to a few thousandths) passes with room.
//   signature 0.95: a faithful copy has the same DOM, so the same boxes (1.00). signature.cjs's
//     labeled set scores a page's own hero rebuilt as a mockup 0.92 to 0.97 and a recolor 1.00, so
//     layout alone cannot see paint drift (pixelRatio carries that); 0.95 is there to catch the
//     gross failures, such as a lost sheet that stacks a grid (0.31 in that set).
const FIDELITY = { pixelRatio: 0.01, signature: 0.95 };

// How many of the pixels the picks change (base against preview) a build may leave unbuilt
// (preview against build), for --match-preview. The page-wide pixelRatio cannot see a pick that
// was never built when the pick is small: bold on two totals moves a few hundred of 1,024,000
// pixels at 1280, far under 0.01. A faithful build differs from the preview only in edge noise
// (the fixture's measures 0), while a pick never built leaves every one of its pixels at the
// base's color (1.00), and a near miss (weight 600 for 700) most of them. 0.25 sits between,
// with room for a build whose text antialiases a little differently.
const MISSED_PICKS = 0.25;

// The capture's 1280 and 390 (capture.cjs VIEWPORTS; a test keeps the two the same), as
// Playwright context options, so a base is shot the way its before shot was.
const SHOT_VIEWPORTS = {
  1280: { viewport: { width: 1280, height: 800 } },
  390: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
};
// How long a shot waits after load and fonts, for late images and short entrance transitions.
const SETTLE_MS = 500;

function readShot(png) {
  const img = decodePng(png);
  if (!img) throw new Error(`fidelity: ${Buffer.isBuffer(png) ? 'PNG bytes' : png} is not an 8-bit RGB or RGBA PNG`);
  return img;
}

// Which pixels differ: a 0/1 mask over the union of the two images (the wider width times the
// taller height), a pixel only one image has counting as different.
function diffMask(pngA, pngB) {
  const a = readShot(pngA), b = readShot(pngB);
  const width = Math.max(a.width, b.width), height = Math.max(a.height, b.height);
  const mask = new Uint8Array(width * height).fill(1);
  const overlapW = Math.min(a.width, b.width), overlapH = Math.min(a.height, b.height);
  let count = width * height - overlapW * overlapH;
  for (let y = 0; y < overlapH; y++) {
    const ra = a.rows[y], rb = b.rows[y];
    for (let x = 0; x < overlapW; x++) {
      const ia = x * a.bpp, ib = x * b.bpp;
      const off = Math.abs(ra[ia] - rb[ib]) > CHANNEL_TOLERANCE
        || Math.abs(ra[ia + 1] - rb[ib + 1]) > CHANNEL_TOLERANCE
        || Math.abs(ra[ia + 2] - rb[ib + 2]) > CHANNEL_TOLERANCE;
      if (off) count++;
      else mask[y * width + x] = 0;
    }
  }
  return { width, height, mask, count };
}

async function compareShots(pngA, pngB, opts = {}) {
  const d = diffMask(pngA, pngB);
  const sigs = opts.signatures;
  const signature = sigs && sigs[0] && sigs[1] ? similarity(sigs[0], sigs[1]) : null;
  return { pixelRatio: d.width * d.height ? d.count / (d.width * d.height) : 0, signature };
}

// --match-preview's measure: the build against the preview of the picks (compareShots), and
// the share of the pixels the picks change (base against preview) that the build does not
// show as the preview does. missed is null when the picks change no pixel at this width.
async function comparePicks(basePng, previewPng, buildPng) {
  const { pixelRatio } = await compareShots(previewPng, buildPng);
  const picked = diffMask(basePng, previewPng), off = diffMask(previewPng, buildPng);
  let both = 0;
  if (picked.width === off.width) {
    for (let i = 0; i < picked.mask.length && i < off.mask.length; i++) if (picked.mask[i] && off.mask[i]) both++;
  } else {
    both = picked.count;  // a build of another size: none of the picks' pixels line up
  }
  return { pixelRatio, picked: picked.count, missed: picked.count ? both / picked.count : null };
}

// Runs in the page: the engine's paint, for a shot outside the review page. Writes the on set to
// <html data-rc> and puts each on change's swaps in place, in spec order (engine.js "swaps").
function applyChanges(on) {
  document.documentElement.setAttribute('data-rc', on.join(' '));
  document.querySelectorAll('template[data-rc-swap]').forEach((tpl) => {
    if (on.indexOf(tpl.dataset.rcSwap) < 0) return;
    let targets;
    try { targets = document.querySelectorAll(tpl.dataset.rcTarget); } catch (e) { return; }
    targets.forEach((el) => {
      const frag = tpl.content.cloneNode(true);
      if (!frag.childNodes.length) return;
      el.parentNode.insertBefore(frag, el);
      el.parentNode.removeChild(el);
    });
  });
}

// A viewport PNG of a base document (the review page's embedded snapshot, with its change CSS
// and swap templates) at one of SHOT_VIEWPORTS' widths, with the given changes on. Shot as a
// page of its own, not through the review page's frame: the frame is scaled to fit its column,
// and the before shot was taken at the capture's device scale with no frame around it.
async function renderBase(browser, doc, width, on = []) {
  const ctx = await browser.newContext(SHOT_VIEWPORTS[width]);
  try {
    const page = await ctx.newPage();
    await page.setContent(doc, { waitUntil: 'load' });
    await page.evaluate(applyChanges, on);
    await page.evaluate(() => document.fonts.ready.then(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))));
    await page.waitForTimeout(SETTLE_MS);
    return await page.screenshot();
  } finally {
    await ctx.close();
  }
}

// The before shot's file names for a snapshot, best first: the capture writes
// <name>-<state>-snapshot.html beside <name>-<state>-<width>.png, so the snapshot's own stem
// first, then <stem>-default-<width>.png for a snapshot named without its state.
function shotNames(snapshotFile, width) {
  const stem = path.basename(snapshotFile).replace(/-snapshot\.html?$/i, '').replace(/\.html?$/i, '');
  return [`${stem}-${width}.png`, `${stem}-default-${width}.png`];
}

module.exports = { compareShots, comparePicks, diffMask, renderBase, shotNames, applyChanges,
  FIDELITY, MISSED_PICKS, CHANNEL_TOLERANCE, SHOT_VIEWPORTS, SETTLE_MS };
