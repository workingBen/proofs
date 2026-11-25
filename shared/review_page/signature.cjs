// Layout signatures, to tell whether two mockups (or a mockup and the page it replaces) are
// the same layout in different paint. Used by smoke.cjs on every item with two or more options,
// and on every item that carries `before_sections`.
//
// layoutSignature(page, boxSelector) resolves to [{ kind, x, y, w, h }]: the box's elements by
//   the visual-qa capture's kinds (heading, text, button, link, image, list, form, badge), each
//   rectangle normalized to the box (0 to 1).
// signatureFromSection(section) is the same for one `measures.sections[i]` from the capture
//   (page px), normalized to the section's own box. A section's left and width are used when the
//   capture gives them; otherwise the box is the content extent (leftmost element edge to
//   rightmost), so a centered column still lines up with a mockup that fills its box.
// similarity(a, b) is 0 to 1: for each element, the best overlap (IoU) with an element of the
//   same kind on the other side, averaged over both sides' elements, times the smaller element
//   count over the larger. Elements with no same-kind partner score 0, so a missing or extra
//   element lowers it twice (once as a miss, once in the count ratio).
//
// Threshold, with its reason: NEAR_COPY = 0.85. A recolor or a font swap of one layout scores
//   about 1.0; a real rearrangement of even a few blocks (stack to two columns) falls under
//   0.5. 0.85 leaves room for sub-pixel and wrapping drift while a changed row still clears it.
//   It is a first value and a later trial may tune it.
const NEAR_COPY = 0.85;

// The classifier below is a copy of the one in skills/visual-qa/scripts/capture.cjs (it runs in
// the page, so it cannot be required). tests.test_review_page.NearCopy compares the two texts,
// so they cannot drift apart unnoticed.
function measureSignature({ selector }) {
  const box = document.querySelector(selector);
  if (!box) return [];
  const visible = (el) => {
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
    }
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const kindOf = (el) => {
    const t = el.tagName.toLowerCase();
    if (/^h[1-6]$/.test(t)) return 'heading';
    if (t === 'p' || t === 'blockquote') return 'text';
    if (t === 'button' || el.getAttribute('role') === 'button' || (t === 'input' && /^(button|submit)$/.test(el.type))) return 'button';
    if (t === 'a') return 'link';
    if (t === 'img') return 'image';
    if (t === 'ul' || t === 'ol') return 'list';
    if (t === 'form') return 'form';
    return 'badge';
  };
  const elementSel = 'h1,h2,h3,h4,h5,h6,p,blockquote,button,[role=button],input[type=button],input[type=submit],'
    + 'a,img,ul,ol,form,[class*=badge],[class*=pill],[class*=chip]';
  // What an element inside one of these is part of, not a separate row (links and images
  // are not containers: a card link still lists its image).
  const holds = new Set(['heading', 'text', 'button', 'list', 'form', 'badge']);
  const br = box.getBoundingClientRect();
  if (!(br.width > 0 && br.height > 0)) return [];
  const taken = new Set();
  const out = [];
  for (const el of box.querySelectorAll(elementSel)) {
    if (out.length >= 40) break;
    if (!visible(el)) continue;
    let inside = false;
    for (let a = el.parentElement; a && a !== box; a = a.parentElement) if (taken.has(a)) { inside = true; break; }
    if (inside) continue;
    const kind = kindOf(el);
    if (holds.has(kind)) taken.add(el);
    const r = el.getBoundingClientRect();
    out.push({ kind, x: (r.left - br.left) / br.width, y: (r.top - br.top) / br.height,
      w: r.width / br.width, h: r.height / br.height });
  }
  return out;
}

async function layoutSignature(page, boxSelector) {
  return page.evaluate(measureSignature, { selector: boxSelector });
}

function signatureFromSection(sec) {
  const els = (sec && sec.elements) || [];
  if (!els.length) return [];
  const given = typeof sec.left === 'number' && typeof sec.width === 'number' && sec.width > 0;
  const left = given ? sec.left : Math.min(...els.map((e) => e.left));
  const width = given ? sec.width : Math.max(...els.map((e) => e.left + e.width)) - left;
  if (!(width > 0)) return [];
  const height = sec.height > 0 ? sec.height : 1;
  return els.map((e) => ({ kind: e.kind, x: (e.left - left) / width, y: (e.top - sec.top) / height,
    w: e.width / width, h: e.height / height }));
}

function iou(a, b) {
  const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
  if (w <= 0 || h <= 0) return 0;
  const inter = w * h;
  return inter / (a.w * a.h + b.w * b.h - inter);
}

function similarity(a, b) {
  if (!a.length || !b.length) return 0;
  const best = (from, to) => from.reduce((sum, e) =>
    sum + Math.max(0, ...to.filter((o) => o.kind === e.kind).map((o) => iou(e, o))), 0);
  const matched = (best(a, b) + best(b, a)) / (a.length + b.length);
  return matched * (Math.min(a.length, b.length) / Math.max(a.length, b.length));
}

module.exports = { layoutSignature, signatureFromSection, similarity, NEAR_COPY };
