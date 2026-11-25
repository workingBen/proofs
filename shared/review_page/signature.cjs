// Layout signatures, to tell whether two mockups (or a mockup and the page it replaces) are
// the same layout in different paint. Used by smoke.cjs on every item with two or more options,
// and on every item that carries `before_sections`.
//
// layoutSignature(page, boxSelector) resolves to [{ kind, x, y, w, h }]: the box's elements by
//   the visual-qa capture's kinds (heading, text, button, link, image, list, form, badge), each
//   rectangle normalized to the box (0 to 1). Text with no painted shape of its own is measured
//   by its text, not its block box (a block box stretches to its container, so a centered line
//   and a full-width one looked the same). Large painted divs with no text, CSS background
//   images, svg, video, canvas and iframes count as `image`, so a placeholder picture is seen.
// signatureFromSection(section) is the same for one `measures.sections[i]` from the capture
//   (page px), normalized to the section's own box: its `layout` list when the capture has one
//   (the same measure as above), else its `elements` (block boxes; older captures). A section's
//   left and width are used when the capture gives them; otherwise the box is the content
//   extent (leftmost element edge to rightmost).
// similarity(a, b) is 0 to 1, symmetric: the mean of the product of four parts read from each
//   side (similarityParts gives the parts, each 0 to 1, averaged the same way). Every element
//   carries a weight, the square root of its area as a share of its side's total, so a 12px
//   badge counts for a few percent of a hero, not one element in six.
//   order    the heaviest common subsequence of the kinds in reading order (top to bottom, a
//            row left to right): the weight that keeps its order. A block moved, added or
//            removed lowers it by that block's weight.
//   columns  each element's best x-interval overlap with one of its kind on the other side,
//            weighted, over both sides: which column a block sits in, blind to vertical
//            shifts. x is measured from the box's center, scaled to the half-width of the
//            larger elements (centered(), below), so a full-bleed section and a mockup box
//            line up and one small badge in a corner cannot rescale the rest.
//   size     the k-th element of each kind paired with the k-th on the other side (wherever it
//            moved), its share of its side's element area within its family (pictures, or
//            everything else), smaller over larger, averaged: a heading made much bigger
//            lowers it; a narrower box (pictures scale, type does not) does not.
//   rank     for each pair matched by order, 1 minus the gap between its places (the middle of
//            its weight along the reading order), weighted; raised to the power 0.5, so it
//            weighs lightly.
//   Why a product, not a weighted sum: a near-copy is the same on every count at once, and one
//   real difference (a mirrored split: order 1.00, size 1.00, columns 0.00) is a real
//   alternative; a sum let matching sizes and order buy back a mirrored layout. Raw y is not
//   used at all, so a spacing-only change (every gap x1.1 to x2) still scores 0.93 to 0.99.
//   Both directions are averaged because, when kinds repeat, the walk through tied pairs
//   depends on which side goes first.
//
// Threshold, with its reason: NEAR_COPY = 0.70 (Task 7b; was 0.30 on the old IoU metric).
//   Tuned on the labeled set in tests.test_review_page.NearCopyLabeled (real mockups at 1280,
//   each scored in both orders, same result): must flag, scored 0.87 to 1.00: recolor only
//   1.00, spacing x1.1 0.99, spacing x1.35 0.97, the same plus one small badge 0.96, a small
//   badge moved to a corner 0.97, text reflowed slightly 0.87. Must not flag, scored 0.00 to
//   0.49: a bigger heading plus moved buttons 0.49, text column vs full width 0.38, stacked vs
//   grid 0.31, stacked vs split 0.13, placeholder picture beside text vs text alone 0.13,
//   mirrored split 0.00. Every label clears 0.70 by at least 0.17 (the test asks for 0.15).
//   Checked against real pages (the Astro and Vue trial heroes, captured fresh): the page's own
//   hero reproduced as a mockup scored 0.97 and 0.92 against the capture; the trial's Step up
//   and Bold options 0.09 to 0.30. One change on its own lands near the cut (only a bigger
//   heading 0.59, only the buttons moved 0.80): a flag there is a prompt to look, then change
//   the option or say in the item's Reason what genuinely differs. A flag is a prompt to look,
//   not proof.
const NEAR_COPY = 0.70;

// The classifier and layout boxes below are copies of those in skills/visual-qa/scripts/capture.cjs (it runs in
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
  // Layout boxes: where an element shows, for the near-copy signature. Text with no painted
  // shape of its own (no background, no border) is measured by its text (the union of its text
  // nodes' line boxes), not its block box, which stretches to whatever holds it. A picture is any
  // large element (at least minArea px) that is media (svg, video, canvas, iframe), has a CSS
  // background image, or is painted (a background color or gradient) and holds no text and none
  // of the elements above: a placeholder div. A candidate at least half covered by an image or a
  // picture already found (a glow or a fade laid over a screenshot) is part of that picture.
  // capture.cjs and signature.cjs share this text (tested).
  const painted = (s) => s.backgroundImage !== 'none' || !/^(transparent|rgba\(0, 0, 0, 0\))$/.test(s.backgroundColor);
  const shaped = (el) => {
    const s = getComputedStyle(el);
    return painted(s) || ['Top', 'Right', 'Bottom', 'Left'].some((side) =>
      s[`border${side}Style`] !== 'none' && parseFloat(s[`border${side}Width`]) > 0);
  };
  const textRect = (el) => {
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity;
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const n = tw.currentNode;
      if (!n.textContent.trim() || !n.parentElement || !visible(n.parentElement)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const q of range.getClientRects()) {
        if (!(q.width > 0 && q.height > 0)) continue;
        l = Math.min(l, q.left); t = Math.min(t, q.top); r = Math.max(r, q.right); b = Math.max(b, q.bottom);
      }
    }
    return l === Infinity ? null : { left: l, top: t, width: r - l, height: b - t };
  };
  const layoutRect = (el, kind) => (kind === 'image' || kind === 'form' || shaped(el)
    ? el.getBoundingClientRect() : textRect(el) || el.getBoundingClientRect());
  const pictureEls = (root, taken, minArea) => {
    const found = [];
    const shots = [...root.querySelectorAll('img')].filter((i) => visible(i)).map((i) => i.getBoundingClientRect());
    const covered = (r, q) => Math.max(0, Math.min(r.right, q.right) - Math.max(r.left, q.left))
      * Math.max(0, Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top)) / (r.width * r.height);
    for (const el of root.querySelectorAll('*')) {
      if (found.length >= 40) break;
      if (el.matches(elementSel)) continue;
      let inside = false;
      for (let a = el.parentElement; a && a !== root; a = a.parentElement) {
        if (taken.has(a) || found.includes(a)) { inside = true; break; }
      }
      if (inside) continue;
      const r = el.getBoundingClientRect();
      if (r.width * r.height < minArea || !visible(el)) continue;
      const s = getComputedStyle(el);
      const media = /^(svg|video|canvas|iframe)$/.test(el.tagName.toLowerCase());
      const empty = !(el.innerText || el.textContent || '').trim() && !el.querySelector(elementSel);
      if (!(media || /url\(/.test(s.backgroundImage) || (painted(s) && empty))) continue;
      if ([...shots, ...found.map((f) => f.getBoundingClientRect())].some((q) => covered(r, q) >= 0.5)) continue;
      found.push(el);
    }
    return found;
  };
  // End of layout boxes.
  const br = box.getBoundingClientRect();
  if (!(br.width > 0 && br.height > 0)) return [];
  const taken = new Set();
  const out = [];
  const push = (kind, r) => out.push({ kind, x: (r.left - br.left) / br.width, y: (r.top - br.top) / br.height,
    w: r.width / br.width, h: r.height / br.height });
  for (const el of box.querySelectorAll(elementSel)) {
    if (out.length >= 40) break;
    if (!visible(el)) continue;
    let inside = false;
    for (let a = el.parentElement; a && a !== box; a = a.parentElement) if (taken.has(a)) { inside = true; break; }
    if (inside) continue;
    const kind = kindOf(el);
    if (holds.has(kind)) taken.add(el);
    push(kind, layoutRect(el, kind));
  }
  for (const el of pictureEls(box, taken, 0.02 * br.width * br.height)) {
    if (out.length >= 40) break;
    push('image', el.getBoundingClientRect());
  }
  return out;
}

async function layoutSignature(page, boxSelector) {
  return page.evaluate(measureSignature, { selector: boxSelector });
}

function signatureFromSection(sec) {
  // `layout` (captures since Task 7b) measures text by its text and lists painted pictures, as
  // measureSignature does; older captures have only `elements`, whose text boxes are block boxes.
  const els = (sec && (Array.isArray(sec.layout) && sec.layout.length ? sec.layout : sec.elements)) || [];
  if (!els.length) return [];
  const given = typeof sec.left === 'number' && typeof sec.width === 'number' && sec.width > 0;
  const left = given ? sec.left : Math.min(...els.map((e) => e.left));
  const width = given ? sec.width : Math.max(...els.map((e) => e.left + e.width)) - left;
  if (!(width > 0)) return [];
  const height = sec.height > 0 ? sec.height : 1;
  return els.map((e) => ({ kind: e.kind, x: (e.left - left) / width, y: (e.top - sec.top) / height,
    w: e.width / width, h: e.height / height }));
}

// Elements in reading order: by top; an element whose top is within ROW_TOL of a row's first
// element and above that element's middle joins its row, and a row reads left to right. (The
// middle test: in a 1196px-tall section 0.02 is 24px, and a 20px eyebrow line 16px above a
// heading was read after it.)
const ROW_TOL = 0.02;
function readingOrder(sig) {
  const byTop = [...sig].sort((p, q) => p.y - q.y || p.x - q.x);
  const rows = [];
  for (const e of byTop) {
    const row = rows[rows.length - 1];
    if (row && e.y - row[0].y <= ROW_TOL && e.y < row[0].y + row[0].h / 2) row.push(e);
    else rows.push([e]);
  }
  return rows.flatMap((row) => row.sort((p, q) => p.x - q.x));
}

// How much an element counts in the order, columns and rank parts: the square root of its area
// (its linear size). A 12px badge then weighs a few percent of a hero, not one element in six,
// while a button still counts for more than a badge. Weights are shares of the side's total.
const weightsOf = (sig) => {
  const raw = sig.map((e) => Math.sqrt(Math.max(0, e.w * e.h)));
  const total = raw.reduce((sum, v) => sum + v, 0) || 1;
  return raw.map((v) => v / total);
};

// x measured from the box's center, scaled so the edge of the content farthest from the center
// sits at 0 or 1. A captured section is often full-bleed (1280px) with its content in a centered
// container (x 0.10 to 0.90), while a mockup fills its box (0.02 to 0.98): measured from the
// box's edges the two never line up. From the center, left, right and centered placement all
// survive (a right-hand column stays right of center); only the side margins drop out. The
// extent counts only elements holding at least EXTENT_SHARE of the side's element area (and
// always the largest), so one small badge in a corner cannot rescale everything else.
const EXTENT_SHARE = 0.05;
function centered(sig) {
  const area = sig.map((e) => e.w * e.h);
  const total = area.reduce((sum, v) => sum + v, 0);
  const top = Math.max(...area);
  const big = sig.filter((e, i) => area[i] >= EXTENT_SHARE * total || area[i] === top);
  const half = Math.max(...big.map((e) => Math.max(Math.abs(e.x - 0.5), Math.abs(e.x + e.w - 0.5))));
  if (!(half > 0)) return sig;
  return sig.map((e) => ({ ...e, x: (e.x - 0.5 + half) / (2 * half), w: e.w / (2 * half) }));
}

// The heaviest common subsequence of the kinds: like the longest one, but a matched pair is worth
// the mean of its two weights, so the result is the share of the layout that keeps its order
// (1 when every element matches in order). Returns the value and the matched index pairs.
function orderPairs(a, b, wa, wb) {
  const n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  const val = (i, j) => (a[i].kind === b[j].kind ? (wa[i] + wb[j]) / 2 : -1);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      const v = val(i, j);
      L[i][j] = Math.max(L[i + 1][j], L[i][j + 1], v >= 0 ? v + L[i + 1][j + 1] : 0);
    }
  }
  const pairs = [];
  const eq = (x, y) => Math.abs(x - y) < 1e-12;
  for (let i = 0, j = 0; i < n && j < m;) {
    const v = val(i, j);
    if (v >= 0 && eq(L[i][j], v + L[i + 1][j + 1])) { pairs.push([i, j]); i++; j++; }
    else if (eq(L[i][j], L[i + 1][j])) i++;
    else j++;
  }
  return { value: L[0][0], pairs };
}

function xOverlap(a, b) {
  const inter = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  if (inter <= 0) return 0;
  return inter / (Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x));
}

// The four parts, read from a's side. The walk through tied pairs depends on which side goes
// first when kinds repeat, so similarityParts and similarity average both directions.
function partsOneWay(a, b) {
  if (!a.length || !b.length) return { order: 0, columns: 0, size: 0, rank: 0 };
  const A = readingOrder(centered(a)), B = readingOrder(centered(b));
  const wa = weightsOf(A), wb = weightsOf(B);
  const { value: order, pairs } = orderPairs(A, B, wa, wb);
  // Columns: each element's best x-interval overlap with one of its kind on the other side
  // (0 when there is none), weighted, over both sides. Blind to vertical position.
  const best = (from, to, w) => from.reduce((sum, e, i) =>
    sum + w[i] * Math.max(0, ...to.filter((o) => o.kind === e.kind).map((o) => xOverlap(e, o))), 0);
  const columns = (best(A, B, wa) + best(B, A, wb)) / 2;
  // Size: for each kind, the k-th element of that kind in reading order paired with the k-th on
  // the other side (wherever it moved: a moved block still has a size), its share of its side's
  // element area within its family (pictures, or everything else), smaller over larger. Families, because a picture scales with the box
  // while type is set in px: the same page reproduced in a 1046px box instead of a 1280px
  // section shifts every text-to-picture share by about (1046/1280)^2 with nothing changed.
  const fam = (e) => (e.kind === 'image' ? 'image' : 'other');
  const totals = (s) => s.reduce((t, e) => { t[fam(e)] = (t[fam(e)] || 0) + e.w * e.h; return t; }, {});
  const ta = totals(A), tb = totals(B);
  const share = (e, t) => (e.w * e.h) / (t[fam(e)] || 1);
  const ratio = (p, q) => (Math.max(p, q) > 0 ? Math.min(p, q) / Math.max(p, q) : 1);
  if (!pairs.length) return { order, columns, size: 0, rank: 0 };
  const byKind = (s) => s.reduce((m, e) => { (m[e.kind] = m[e.kind] || []).push(e); return m; }, {});
  const ka = byKind(A), kb = byKind(B);
  const same = Object.keys(ka).flatMap((k) => (kb[k] || []).slice(0, ka[k].length).map((q, n) => [ka[k][n], q]));
  const size = same.reduce((sum, [p, q]) => sum + ratio(share(p, ta), share(q, tb)), 0) / same.length;
  // Rank: each matched pair's place in its side's reading order, compared, weighted like order.
  // A place is the middle of the element's weight along the reading order (0 to 1), so a small
  // element added at the top barely moves the rest.
  const places = (w) => { let run = 0; return w.map((v) => { const p = run + v / 2; run += v; return p; }); };
  const pa = places(wa), pb = places(wb);
  const pw = pairs.map(([i, j]) => (wa[i] + wb[j]) / 2);
  const pwt = pw.reduce((sum, v) => sum + v, 0) || 1;
  const rank = pairs.reduce((sum, [i, j], k) => sum + pw[k] * (1 - Math.abs(pa[i] - pb[j])), 0) / pwt;
  return { order, columns, size, rank };
}

// Exponents of the product (see the header for why a product and why these).
const WEIGHTS = { order: 1, columns: 1, size: 1, rank: 0.5 };
const product = (parts) => Object.keys(WEIGHTS).reduce((p, k) => p * Math.pow(parts[k], WEIGHTS[k]), 1);

// The four parts of the similarity, each 0 to 1, the mean of both directions (for the report).
function similarityParts(a, b) {
  const x = partsOneWay(a, b), y = partsOneWay(b, a);
  return Object.fromEntries(Object.keys(x).map((k) => [k, (x[k] + y[k]) / 2]));
}

// Symmetric: the mean of the two directions' products.
function similarity(a, b) {
  return (product(partsOneWay(a, b)) + product(partsOneWay(b, a))) / 2;
}

module.exports = { layoutSignature, signatureFromSection, similarity, similarityParts, WEIGHTS, NEAR_COPY };
