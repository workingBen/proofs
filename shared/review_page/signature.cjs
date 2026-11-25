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
// similarity(a, b) is 0 to 1, the product of four parts, each 0 to 1 (similarityParts):
//   order    the longest common subsequence of the kinds in reading order (top to bottom, a row
//            left to right) over the longer list: a block moved, added or removed lowers it.
//   columns  each element's best x-interval overlap with one of its kind on the other side,
//            averaged over both sides: which column a block sits in, blind to vertical shifts.
//            x is measured from the box's center, scaled to the content's half-width
//            (centered(), below), so a full-bleed section and a mockup box line up.
//   size     for each pair matched by the subsequence, its share of its side's element area
//            within its family (pictures, or everything else), smaller over larger, averaged:
//            a heading made much bigger lowers it; a narrower box (pictures scale, type does not)
//            does not.
//   rank     for each matched pair, 1 minus the gap between its places in the two reading
//            orders (0 first, 1 last), averaged; raised to the power 0.5, so it weighs lightly.
//   Why a product, not a weighted sum: a near-copy is the same on every count at once, and one
//   real difference (a mirrored split: order 1.00, size 1.00, columns 0.00) is a real
//   alternative; a sum let matching sizes and order buy back a mirrored layout. Raw y is not
//   used at all, so a spacing-only change (every gap x1.1 to x2) still scores 0.87 to 0.99.
//
// Threshold, with its reason: NEAR_COPY = 0.70 (Task 7b; was 0.30 on the old IoU metric).
//   Tuned on the labeled set in tests.test_review_page.NearCopyLabeled (real mockups at 1280):
//   must flag, scored 0.87 to 1.00: recolor only 1.00, spacing x1.1 0.98, spacing x1.35 0.95,
//   text reflowed slightly 0.87. Must not flag, scored 0.00 to 0.39: a bigger heading plus moved
//   buttons 0.39, text column vs full width 0.37, stacked vs grid 0.28, stacked vs split 0.15,
//   placeholder picture beside text vs text alone 0.10, mirrored split 0.00. Every label clears
//   0.70 by at least 0.17 (the test asks for 0.10). Checked against real pages (the Astro and
//   Vue trial heroes, captured fresh): the page's own hero reproduced as a mockup scored 0.96
//   and 0.86 against the capture; the trial's Step up and Bold options 0.10 to 0.20. One change
//   on its own lands near the cut (only a bigger heading 0.61, only the buttons moved 0.75):
//   a flag there is a prompt to look, then change the option or say in the item's Reason what
//   genuinely differs. A flag is a prompt to look, not proof.
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

// x measured from the box's center, scaled so the content's farthest edge from the center sits
// at 0 or 1. A captured section is often full-bleed (1280px) with its content in a centered
// container (x 0.10 to 0.90), while a mockup fills its box (0.02 to 0.98): measured from the
// box's edges the two never line up. From the center, left, right and centered placement all
// survive (a right-hand column stays right of center); only the side margins drop out.
function centered(sig) {
  const half = Math.max(...sig.map((e) => Math.max(Math.abs(e.x - 0.5), Math.abs(e.x + e.w - 0.5))));
  if (!(half > 0)) return sig;
  return sig.map((e) => ({ ...e, x: (e.x - 0.5 + half) / (2 * half), w: e.w / (2 * half) }));
}

// Longest common subsequence of the kinds, with the matched index pairs.
function lcsPairs(a, b) {
  const n = a.length, m = b.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      L[i][j] = a[i].kind === b[j].kind ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
    }
  }
  const pairs = [];
  for (let i = 0, j = 0; i < n && j < m;) {
    if (a[i].kind === b[j].kind && L[i][j] === L[i + 1][j + 1] + 1) { pairs.push([i, j]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) i++;
    else j++;
  }
  return pairs;
}

function xOverlap(a, b) {
  const inter = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
  if (inter <= 0) return 0;
  return inter / (Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x));
}

// The four parts of the similarity, each 0 to 1 (exported for the report and the tests).
function similarityParts(a, b) {
  if (!a.length || !b.length) return { order: 0, columns: 0, size: 0, rank: 0 };
  const A = readingOrder(centered(a)), B = readingOrder(centered(b));
  const pairs = lcsPairs(A, B);
  const order = pairs.length / Math.max(A.length, B.length);
  // Columns: each element's best x-interval overlap with an element of its kind on the other
  // side (0 when there is none), averaged over both sides. Blind to vertical position.
  const best = (from, to) => from.reduce((sum, e) =>
    sum + Math.max(0, ...to.filter((o) => o.kind === e.kind).map((o) => xOverlap(e, o))), 0);
  const columns = (best(A, B) + best(B, A)) / (A.length + B.length);
  // Size: each matched pair's share of its side's element area within its family (pictures,
  // or everything else), smaller over larger. Families, because a picture scales with the box
  // while type is set in px: the same page reproduced in a 1046px box instead of a 1280px
  // section shifts every text-to-picture share by about (1046/1280)^2 with nothing changed.
  const fam = (e) => (e.kind === 'image' ? 'image' : 'other');
  const totals = (s) => s.reduce((t, e) => { t[fam(e)] = (t[fam(e)] || 0) + e.w * e.h; return t; }, {});
  const ta = totals(A), tb = totals(B);
  const share = (e, t) => (e.w * e.h) / (t[fam(e)] || 1);
  const ratio = (p, q) => (Math.max(p, q) > 0 ? Math.min(p, q) / Math.max(p, q) : 1);
  const mean = (f) => (pairs.length ? pairs.reduce((sum, [i, j]) => sum + f(A[i], B[j], i, j), 0) / pairs.length : 0);
  const size = mean((p, q) => ratio(share(p, ta), share(q, tb)));
  // Rank: each matched pair's place in its side's reading order (0 first, 1 last), compared.
  const place = (i, n) => (n > 1 ? i / (n - 1) : 0.5);
  const rank = mean((p, q, i, j) => 1 - Math.abs(place(i, A.length) - place(j, B.length)));
  return { order, columns, size, rank };
}

// Exponents of the product (see the header for why a product and why these).
const WEIGHTS = { order: 1, columns: 1, size: 1, rank: 0.5 };

function similarity(a, b) {
  const parts = similarityParts(a, b);
  return Object.keys(WEIGHTS).reduce((p, k) => p * Math.pow(parts[k], WEIGHTS[k]), 1);
}

module.exports = { layoutSignature, signatureFromSection, similarity, similarityParts, WEIGHTS, NEAR_COPY };
