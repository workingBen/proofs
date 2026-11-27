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
// >= FIDELITY.signature.

const path = require('path');
const { similarity } = require('./signature.cjs');

// decodePng lives in the capture (it also cuts the full shots into parts); reused, not copied.
const { decodePng } = require(path.join(__dirname, '..', '..', 'skills', 'visual-qa', 'scripts', 'capture.cjs'));

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

function readShot(png) {
  const img = decodePng(png);
  if (!img) throw new Error(`fidelity: ${Buffer.isBuffer(png) ? 'PNG bytes' : png} is not an 8-bit RGB or RGBA PNG`);
  return img;
}

async function compareShots(pngA, pngB, opts = {}) {
  const a = readShot(pngA), b = readShot(pngB);
  const width = Math.max(a.width, b.width), height = Math.max(a.height, b.height);
  const overlapW = Math.min(a.width, b.width), overlapH = Math.min(a.height, b.height);
  let differing = width * height - overlapW * overlapH;
  for (let y = 0; y < overlapH; y++) {
    const ra = a.rows[y], rb = b.rows[y];
    for (let x = 0; x < overlapW; x++) {
      const ia = x * a.bpp, ib = x * b.bpp;
      if (Math.abs(ra[ia] - rb[ib]) > CHANNEL_TOLERANCE
        || Math.abs(ra[ia + 1] - rb[ib + 1]) > CHANNEL_TOLERANCE
        || Math.abs(ra[ia + 2] - rb[ib + 2]) > CHANNEL_TOLERANCE) differing++;
    }
  }
  const sigs = opts.signatures;
  const signature = sigs && sigs[0] && sigs[1] ? similarity(sigs[0], sigs[1]) : null;
  return { pixelRatio: width * height ? differing / (width * height) : 0, signature };
}

module.exports = { compareShots, FIDELITY, CHANNEL_TOLERANCE };
