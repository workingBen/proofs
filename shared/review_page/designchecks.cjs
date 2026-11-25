// Design checks on one mockup's box in a built review page: text contrast, small tap targets,
// long lines, near-miss left edges, and type sizes off the page's own scale. Shared by the
// review page smoke check (every variant of every item, at 1280 and 390 px wide).
//
// designChecks(page, boxSelector, { width, beforeFontSizes }) resolves to
//   { contrast: [{ text, ratio, needed }], unmeasured: [{ text, reason }],
//     smallTargets: [{ text, w, h }], longLines: [{ text, chars }],
//     edges: [{ a, b, px }], offScale: [{ text, size }] }
// Small targets are listed only at 390 and long lines only at 1280 (the widths those rules
// are about); the other lists are measured at whatever width the page is at. `offScale` is a
// note for the reader, never a problem: it is empty when `beforeFontSizes` is empty.
//
// Thresholds, each with its reason:
//   contrast 4.5:1, or 3:1 for text of 24px+ (18.66px+ when bold): WCAG 2.x AA.
//   tap target 44x44 px: Apple HIG and WCAG 2.5.5. Links that sit inline in a sentence are
//     exempt, as WCAG exempts them.
//   line length 80 characters: the upper bound of the usual 45-80 readable range.
//   edges 1-6 px apart: 6 px or less reads as a mistake, more reads as a choice.
//   off scale 1 px: a size more than 1 px from every size the page already uses.
// Text over a background image or gradient cannot be measured: it goes in `unmeasured`.

// Runs in the page through page.evaluate, so it must stay self-contained.
function measureBox({ selector, width, beforeFontSizes }) {
  const out = { contrast: [], unmeasured: [], smallTargets: [], longLines: [], edges: [], offScale: [] };
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
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a),
    b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  // The color under an element: the stack of translucent layers down to the first opaque one
  // (white when there is none), or null when an ancestor paints an image or gradient.
  const backdrop = (el) => {
    const layers = [];
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.backgroundImage !== 'none') return null;
      const c = parse(s.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a === 1) break; }
    }
    let under = { r: 255, g: 255, b: 255, a: 1 };
    for (let i = layers.length - 1; i >= 0; i--) under = over(layers[i], under);
    return under;
  };

  const seen = new Set();
  const sizes = new Set();
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
    const bg = backdrop(el);
    if (!bg) { out.unmeasured.push({ text: text.slice(0, 40), reason: 'background image or gradient' }); continue; }
    const fg = parse(s.color);
    if (!fg) continue;
    const top = over(fg, bg);
    const [hi, lo] = [lum(top), lum(bg)].sort((x, y) => y - x);
    const ratio = Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
    const needed = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700) ? 3 : 4.5;
    if (ratio < needed) out.contrast.push({ text: text.slice(0, 40), ratio, needed });
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
  return out;
}

async function designChecks(page, boxSelector, { width, beforeFontSizes = [] } = {}) {
  return page.evaluate(measureBox, { selector: boxSelector, width, beforeFontSizes });
}

module.exports = { designChecks };
