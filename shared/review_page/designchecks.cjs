// Design checks on one mockup's box in a built review page: text contrast, small tap targets,
// long lines, near-miss left edges, and type sizes off the page's own scale. Shared by the
// review page smoke check (every option of every design-review item, at 1280 and 390 px wide).
//
// designChecks(page, boxSelector, { width, beforeFontSizes }) resolves to
//   { contrast: [{ text, ratio, needed }], unmeasured: [{ text, reason }],
//     smallTargets: [{ text, w, h }], longLines: [{ text, chars }],
//     edges: [{ a, b, px }], offScale: [{ text, size }],
//     clippedRows: [{ text, cut, px, hidden }], peekRows: [{ text, cut, px }] }
// Small targets, clipped rows and peeks are listed only at 390 and long lines only at 1280 (the
// widths those rules are about); the other lists are measured at whatever width the page is at.
// `offScale` and `peekRows` are notes for the reader, never problems: `offScale` is empty when
// `beforeFontSizes` is empty.
// A clipped row is a sideways scroller (overflow-x auto, scroll, hidden or clip, content wider
// than its box) whose item is only partly visible at its right edge, or the viewport's, or whose
// items sit wholly past that edge: the page never scrolls sideways and a phone shows no
// scrollbar, so nothing else sees a nav link cut mid-word or never shown. `text` is the cut
// item's whole label, `cut` the part a reader sees, `px` how far it runs past the edge (null,
// null and 0 when no item is partly visible); `hidden` lists the labels wholly past it. Measured with
// the row scrolled to its start, as a reader first sees it. A wrapper wider than the scroller
// (nav > ul > li) is looked through to its own items.
//
// Thresholds, each with its reason:
//   contrast 4.5:1, or 3:1 for text of 24px+ (18.66px+ when bold): WCAG 2.x AA.
//   tap target 44x44 px: Apple HIG and WCAG 2.5.5. Links that sit inline in a sentence are
//     exempt, as WCAG exempts them.
//   line length 80 characters: the upper bound of the usual 45-80 readable range.
//   edges 1-6 px apart: 6 px or less reads as a mistake, more reads as a choice.
//   off scale 1 px: a size more than 1 px from every size the page already uses.
//   clipped row 1 px: an item runs more than 1 px past the edge (hidden when it starts there). An item wider than half the
//     scroller that holds more than one line of text or a picture is a card, and a partly shown
//     next card is a deliberate swipe peek (`peekRows`, a note): a phone carousel shows one card
//     and a slice of the next, so its cards run past half the row. Width alone is not enough:
//     in the review page's 292 px box at 390, the hillock nav's "Works with AI helpers" link was
//     139 px of a 264 px row (53%), so a one-line label of any width counts as a link, tab,
//     button or chip, and cut. Items without text (a decorative shape bleeding off a
//     hidden-overflow box) are not counted.
// Text over an image, video, canvas, SVG, background image or gradient cannot be measured: it
// goes in `unmeasured`, and smoke says so in its `notes` so "not measured" never reads as "clean".
// So does a color the browser cannot paint to a 1x1 canvas, and a translucent element over its
// own background; text faded by an opacity below 1 inside the box is composited and measured.

// Runs in the page through page.evaluate, so it must stay self-contained.
function measureBox({ selector, width, beforeFontSizes }) {
  const out = { contrast: [], unmeasured: [], smallTargets: [], longLines: [], edges: [], offScale: [],
    clippedRows: [], peekRows: [] };
  const box = document.querySelector(selector);
  if (!box) return out;
  const shown = (el) => {
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
    }
    return true;
  };
  const label = (el) => (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || el.tagName.toLowerCase())
    .trim().replace(/\s+/g, ' ').slice(0, 40);
  // Any CSS color (rgb, hsl, oklch, color(), a named color) to sRGB through a 1x1 canvas: the
  // browser converts it and the pixel is read back. Tailwind v4 computes to oklch(), which a
  // plain rgb() parse skipped silently. null when the browser cannot paint it.
  const cv = document.createElement('canvas');
  cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const memo = new Map();
  const parse = (c) => {
    if (memo.has(c)) return memo.get(c);
    let out = null;
    const m = /^rgba?\(([^)]+)\)$/.exec(c.trim());
    if (m) {
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      if (p.length >= 3 && p.every((n) => Number.isFinite(n))) out = { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    if (!out && cx && c && CSS.supports('color', c)) {
      cx.clearRect(0, 0, 1, 1);
      cx.fillStyle = '#000';
      cx.fillStyle = c;
      cx.fillRect(0, 0, 1, 1);
      const d = cx.getImageData(0, 0, 1, 1).data;
      out = { r: d[0], g: d[1], b: d[2], a: Math.round((d[3] / 255) * 1000) / 1000 };
    }
    memo.set(c, out);
    return out;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a),
    b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  // The color under an element and what the text's own paint is multiplied by: { bg, fade },
  // or { why } when it cannot be measured. bg is the stack of translucent layers down to the
  // first opaque one (white, the browser's canvas, only when nothing at all is painted). An
  // element inside the mockup box with opacity below 1 fades the text (fade); when a background
  // layer sits inside that faded element too, the composite is not a flat color, so unmeasured.
  const TRANSLUCENT = 'contrast: not measured (a translucent element over its own background)';
  const backdrop = (el) => {
    const layers = [];
    let fade = 1;
    let opaque = null;
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.backgroundImage !== 'none') return { why: 'contrast: not measured (text over an image or gradient)' };
      const c = parse(s.backgroundColor);
      if (!c) return { why: `contrast: not measured (background color ${s.backgroundColor} could not be read)` };
      if (box.contains(a) && Number(s.opacity) < 1) {
        if (layers.length || c.a > 0) return { why: TRANSLUCENT };
        fade *= Number(s.opacity);
      }
      if (c.a > 0) { layers.push(c); if (c.a === 1) { opaque = a; break; } }
    }
    // Past the first opaque background, a faded element inside the box fades that background
    // and the text together, which is the same translucent case: unmeasured, never a full pass.
    for (let a = opaque && opaque.parentElement; a && box.contains(a); a = a.parentElement) {
      if (Number(getComputedStyle(a).opacity) < 1) return { why: TRANSLUCENT };
    }
    let under = { r: 255, g: 255, b: 255, a: 1 };
    for (let k = layers.length - 1; k >= 0; k--) under = over(layers[k], under);
    return { bg: under, fade };
  };

  // Clipped rows, before the contrast pass below scrolls elements into view (and so scrollers).
  if (width === 390) {
    const vw = document.documentElement.clientWidth;
    const CLIPS = /^(auto|scroll|hidden|clip)$/;
    for (const row of [box, ...box.querySelectorAll('*')]) {
      if (!CLIPS.test(getComputedStyle(row).overflowX) || row.scrollWidth <= row.clientWidth + 1 || !shown(row)) continue;
      const saved = row.scrollLeft;
      row.scrollLeft = 0;
      try {
        const rr = row.getBoundingClientRect();
        // The visible right edge: the row's padding box, then every clipping ancestor, then the viewport.
        let right = Math.min(rr.left + row.clientLeft + row.clientWidth, vw);
        for (let a = row.parentElement; a; a = a.parentElement) {
          if (a !== document.documentElement && a !== document.body && CLIPS.test(getComputedStyle(a).overflowX)) {
            const ar = a.getBoundingClientRect();
            right = Math.min(right, ar.left + a.clientLeft + a.clientWidth);
          }
        }
        const visible = (k) => shown(k) && k.getBoundingClientRect().width > 0;
        let kids = Array.from(row.children).filter(visible);
        for (let depth = 0; depth < 4 && kids.length === 1 && kids[0].getBoundingClientRect().width > row.clientWidth + 1; depth++) {
          kids = Array.from(kids[0].children).filter(visible);
        }
        // Each text item: the part a reader sees (the characters that end inside the edge), and
        // whether it is a card: wider than half the row AND more than one line of text or a picture.
        // A one-line label of any width is a link, tab, button or chip.
        const inspect = (k, kr) => {
          let seenText = '';
          const tops = new Set();
          const tw = document.createTreeWalker(k, NodeFilter.SHOW_TEXT);
          while (tw.nextNode()) {
            const n = tw.currentNode;
            for (let i = 0; i < n.textContent.length; i++) {
              const r = document.createRange();
              r.setStart(n, i); r.setEnd(n, i + 1);
              const b = r.getBoundingClientRect();
              if (b.width === 0 && b.height === 0) continue;
              if (b.width > 0) tops.add(Math.round(b.top / 3));
              if (b.right <= right + 0.5) seenText += n.textContent[i];
            }
          }
          const card = kr.width > row.clientWidth * 0.5 && (tops.size > 1 || !!k.querySelector('img,picture,video,canvas,svg'));
          return { seen: seenText.trim().replace(/\s+/g, ' ').slice(0, 40), card };
        };
        let cut = null;
        const hidden = [];
        for (const k of kids) {
          if (!(k.innerText || k.textContent || '').trim()) continue;
          const kr = k.getBoundingClientRect();
          if (kr.right <= right + 1) continue;
          const it = inspect(k, kr);
          if (kr.left < right - 1) {
            // Partly visible: a cut link, or a carousel's peeking card (a note).
            const hit = { text: label(k), cut: it.seen, px: Math.round(kr.right - right) };
            if (it.card) out.peekRows.push(hit); else cut = hit;
          } else if (!it.card) {
            // Wholly past the edge: a phone shows no scrollbar, so the reader never knows it is there.
            hidden.push(label(k));
          }
        }
        if (cut || hidden.length) out.clippedRows.push({ text: cut ? cut.text : null, cut: cut ? cut.cut : null,
          px: cut ? cut.px : 0, hidden });
      } finally {
        row.scrollLeft = saved;
      }
    }
  }

  const seen = new Set();
  const sizes = new Set();
  box.setAttribute('data-rp-probe', '');
  const probe = document.createElement('style');
  probe.textContent = '[data-rp-probe], [data-rp-probe] * { pointer-events: auto !important; }';
  document.head.appendChild(probe);
  try {
    const tw = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const node = tw.currentNode;
      const el = node.parentElement;
      const text = node.textContent.trim().replace(/\s+/g, ' ');
      if (!el || !text || el.closest('svg,script,style') || !shown(el)) continue;
      const s = getComputedStyle(el);
      const px = parseFloat(s.fontSize);
      if (beforeFontSizes.length && !beforeFontSizes.some((b) => Math.abs(b - px) <= 1) && !sizes.has(el)) {
        sizes.add(el);
        out.offScale.push({ text: text.slice(0, 40), size: Math.round(px * 100) / 100 });
      }
      // Long lines: the most characters the browser put on one line of this text.
      if (width === 1280 && text.length > 80) {
        const lines = {};
        for (let i = 0; i < node.textContent.length; i++) {
          const r = document.createRange();
          r.setStart(node, i); r.setEnd(node, i + 1);
          const b = r.getBoundingClientRect();
          if (b.width === 0) continue;
          const k = Math.round(b.top);
          lines[k] = (lines[k] || 0) + 1;
        }
        const chars = Math.max(0, ...Object.values(lines));
        if (chars > 80) out.longLines.push({ text: text.slice(0, 40), chars });
      }
      if (seen.has(el)) continue;
      seen.add(el);
      const reason = 'contrast: not measured (text over an image or gradient)';
      // Anything painted under (or over) the text's first line that is not one of its ancestors: an
      // image, video, canvas or SVG, or an overlay with a background image, makes a flat color wrong.
      // Every element in the box takes the pointer while this runs (the style below), so a
      // pointer-events:none scrim is still found.
      const range = document.createRange();
      range.selectNodeContents(node);
      const rect = Array.from(range.getClientRects()).find((r) => r.width > 0 && r.height > 0);
      let covered = false;
      if (rect) {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const at = Array.from(range.getClientRects()).find((r) => r.width > 0 && r.height > 0);
        covered = document.elementsFromPoint(at.left + at.width / 2, at.top + at.height / 2)
          .some((u) => u !== el && !u.contains(el) && (/^(img|picture|video|canvas|svg)$/i.test(u.tagName)
            || u.closest('svg') || getComputedStyle(u).backgroundImage !== 'none'));
      }
      if (covered) { out.unmeasured.push({ text: text.slice(0, 40), reason }); continue; }
      const under = backdrop(el);
      if (under.why) { out.unmeasured.push({ text: text.slice(0, 40), reason: under.why }); continue; }
      const bg = under.bg;
      const ink = parse(s.color);
      if (!ink) { out.unmeasured.push({ text: text.slice(0, 40), reason: `contrast: not measured (text color ${s.color} could not be read)` }); continue; }
      const fg = { ...ink, a: ink.a * under.fade };
      const top = over(fg, bg);
      const [hi, lo] = [lum(top), lum(bg)].sort((x, y) => y - x);
      const ratio = Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
      const needed = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700) ? 3 : 4.5;
      if (ratio < needed) out.contrast.push({ text: text.slice(0, 40), ratio, needed });
    }
  } finally {
    probe.remove();
    box.removeAttribute('data-rp-probe');
  }

  if (width === 390) {
    for (const el of box.querySelectorAll('a, button, [role=button], input, select')) {
      if (!shown(el)) continue;
      if (el.tagName === 'A' && getComputedStyle(el).display === 'inline') continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      if (r.width < 44 || r.height < 44) out.smallTargets.push({ text: label(el), w: Math.round(r.width), h: Math.round(r.height) });
    }
  }

  // Edges: the left edges of a block's direct block children that nearly line up.
  const name = (e) => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim()
    ? '.' + e.className.trim().split(/\s+/)[0] : '') + ' "' + label(e).slice(0, 20) + '"';
  for (const parent of [box, ...box.querySelectorAll('*')]) {
    if (getComputedStyle(parent).display !== 'block') continue;
    const kids = Array.from(parent.children).filter((k) => shown(k) && getComputedStyle(k).display === 'block'
      && k.getBoundingClientRect().width > 0);
    for (let i = 0; i < kids.length; i++) {
      for (let j = i + 1; j < kids.length; j++) {
        const d = Math.abs(kids[i].getBoundingClientRect().left - kids[j].getBoundingClientRect().left);
        if (d >= 1 && d <= 6) out.edges.push({ a: name(kids[i]), b: name(kids[j]), px: Math.round(d * 10) / 10 });
      }
    }
  }
  window.scrollTo(0, 0);
  return out;
}

async function designChecks(page, boxSelector, { width, beforeFontSizes = [] } = {}) {
  return page.evaluate(measureBox, { selector: boxSelector, width, beforeFontSizes });
}

module.exports = { designChecks };
