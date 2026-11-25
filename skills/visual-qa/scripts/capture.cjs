#!/usr/bin/env node
// Visual QA capture: screenshots + measurements for whole pages at three viewports.
//
//   node <skill folder>/scripts/capture.cjs pages.json [--out DIR] [--sizes 390,1440] [--evidence before|after] [--no-scroll] [--compare EARLIER/measures.json]
//
// pages.json (see pages.example.json beside this file):
//   {
//     "base": "http://localhost:3000",
//     "setup": "signin.cjs",            // optional: module exporting async (page, base) => {}
//     "minText": 16, "minTap": 44,       // optional target overrides
//     "pages": [
//       { "name": "pricing", "path": "/pricing" },
//       { "name": "list", "state": "full", "path": "/list", "items": ".line",
//         "actions": [{ "click": "summary" }, { "waitFor": ".editor" }] }
//     ]
//   }
// A bare list of pages ([{"name": "home", "path": "/"}]) is taken too, when PROOFS_BASE_URL
// gives the base (as it does under with_server.py).
//
// --sizes picks viewports by label (default: all of 1440, 1280, 390), or adds a desktop width
// such as 1040 (400 to 2560), for a shot just above a breakpoint.
// PROOFS_BASE_URL, when set, replaces "base" (so it runs unchanged after with_server.py --).
// --evidence <label> prefixes every file the run writes with "<label>-" (a before and an
// after run can share one --out) and also writes <out>/<label>.json in the shape pr-qa reads.
// Before the shots and the measures, each page is scrolled to the bottom in steps and back to
// the top (--no-scroll skips it), so sections that fade in as they scroll into view and lazy
// images are there (Astro run 1: every full-page shot was blank below the hero). A shot that is
// still mostly one flat color below the first screen, or a page with several blocks still at
// opacity 0, is flagged "blank or hidden content": nothing there was checked.
// Each address is base and path joined with exactly one slash ("http://host:3311/" + "/" is
// "http://host:3311/", never "//", which SvelteKit answers with its 404 page).
//
// Exit codes: 0 every page captured; 1 bad arguments or pages file (one plain line on stderr);
// 2 Playwright missing; 3 the browser ignored the viewport (not trustworthy); 6 a page
// answered HTTP 400 or above, or rendered an error page ("Not Found"): that shot is not the
// page, so it is left out of the evidence and listed under "failures", and nothing may call
// the run clean.
//
// Writes <out>/<name>-<state>-<width>.png, ...-full.png, measures.json and summary.md.
// A page taller than one part (4 widths, at most 1,600 px) is also cut into ...-part-NN.png, one
// PNG pixel per CSS pixel, with each part's y range in measures.json ("parts"): an image reader
// shrinks a tall full-page shot until nothing in it is legible (Astro run 3: 31,354 px at 2x). A
// full shot that would pass 16,384 px at the device scale is taken at 1x ("fullScale").
// The site's logo is cropped to <name>-logo-<width>.png ("logo": file, box, source; null when none).
// Each mid-word break names its element, the heading above it, its y and its part ("midWordAt").
// --compare takes an earlier run's measures.json and lists, per page, size and check, the entries
// that are new since then, by text, not by count ("newSince"): a fix that took small tap targets
// from 11 to 9 had made 3 of the 9 (Astro run 3).
// Prints only the summary table, so the run stays small in context.

const fs = require('fs');
const os = require('os');
const path = require('path');

// Same launch order as the review-page smoke check: Playwright's own browser if it is
// installed, else the installed Google Chrome (no download), with the flag that stops
// Chrome on macOS copying its whole app (about 1.4 GB) into a temp folder per launch.
const LAUNCH = path.join(__dirname, '..', '..', '..', 'shared', 'review_page', 'launch.cjs');
let launchChromium, HOW_TO, midWordBreaks;
try {
  ({ launchChromium, HOW_TO } = require(LAUNCH));
  ({ midWordBreaks } = require(path.join(path.dirname(LAUNCH), 'midword.cjs')));
} catch (_) {
  console.error(`Cannot find ${LAUNCH}. Install the whole Proofs plugin, not the visual-qa folder on its own.`);
  process.exit(2);
}

function loadPlaywright() {
  const tries = [
    process.env.PROOFS_PLAYWRIGHT,
    process.env.PLAYWRIGHT_PATH,
    'playwright',
    path.join(process.cwd(), 'node_modules/playwright'),
    path.join(os.homedir(), '.cache', 'proofs-playwright', 'node_modules', 'playwright'),
  ].filter(Boolean);
  for (const t of tries) { try { return require(t); } catch (_) {} }
  console.error('Playwright not found. Set PROOFS_PLAYWRIGHT (or PLAYWRIGHT_PATH) to a node_modules/playwright directory, or install it once.\n' + HOW_TO);
  process.exit(2);
}

const VIEWPORTS = [
  { label: '1440', width: 1440, height: 900 },
  { label: '1280', width: 1280, height: 800 },
  { label: '390', width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 },
];

// Any other whole-number width in this range is a desktop viewport too, for a shot just
// above a CSS breakpoint the change adds (pr-qa: lg: at 1024 gets 1040).
const EXTRA_MIN = 400, EXTRA_MAX = 2560;
const extraWidth = (label) => label !== '1440' && label !== '390';

// The named viewports in their usual order, then extra widths widest first, then the phone.
function pickViewports(sizes) {
  const named = VIEWPORTS.filter((v) => sizes.includes(v.label));
  const extra = [...new Set(sizes.filter((s) => /^\d+$/.test(s) && !VIEWPORTS.some((v) => v.label === s))
    .map(Number).filter((w) => w >= EXTRA_MIN && w <= EXTRA_MAX))]
    .sort((a, b) => b - a).map((w) => ({ label: String(w), width: w, height: 900 }));
  const phone = named.filter((v) => v.isMobile);
  return [...named.filter((v) => !v.isMobile), ...extra, ...phone];
}

// Base and path with exactly one slash between them, whatever either looks like. A path that
// is a whole URL is used as is; one that starts with "?" or "#" goes straight onto the base.
function joinUrl(base, p) {
  const pathPart = p == null ? '' : String(p);
  if (/^[a-z][a-z0-9+.-]*:/i.test(pathPart)) return pathPart;
  const b = String(base || '');
  if (pathPart.startsWith('?') || pathPart.startsWith('#')) return b + pathPart;
  const scheme = (b.match(/^[a-z][a-z0-9+.-]*:\/\/\/?/i) || [''])[0];
  const head = scheme + b.slice(scheme.length).replace(/\/+$/, '');
  return head + '/' + pathPart.replace(/^\/+/, '');
}

class PagesFileError extends Error {}

// The pages file, checked, or a PagesFileError whose message is one plain line.
function readPagesFile(cfgPath, envBase) {
  let text;
  try {
    text = fs.readFileSync(cfgPath, 'utf8');
  } catch (e) {
    throw new PagesFileError(`${cfgPath}: cannot read the pages file (${e.code || e.message})`);
  }
  let cfg;
  try {
    cfg = JSON.parse(text);
  } catch (e) {
    throw new PagesFileError(`${cfgPath}: is not valid JSON (${String(e.message).split('\n')[0]})`);
  }
  const example = path.join(__dirname, 'pages.example.json');
  const shape = `{"base": "http://localhost:3000", "pages": [{"name": "home", "path": "/"}]}; see ${example}`;
  // A bare list of pages is the pages list (Astro runs 1 and 2: pr-qa wrote one first both
  // times); its base comes from PROOFS_BASE_URL, which with_server.py sets.
  if (Array.isArray(cfg)) cfg = { pages: cfg, bareList: true };
  if (!cfg || typeof cfg !== 'object') {
    throw new PagesFileError(`${cfgPath}: needs a top-level "pages" list, as in ${shape}`);
  }
  if (!('pages' in cfg)) throw new PagesFileError(`${cfgPath}: needs a top-level "pages" list, as in ${shape}`);
  if (!Array.isArray(cfg.pages)) throw new PagesFileError(`${cfgPath}: "pages" must be a list, as in ${shape}`);
  if (!cfg.pages.length) throw new PagesFileError(`${cfgPath}: "pages" is empty; list at least one page, as in ${shape}`);
  cfg.pages.forEach((p, i) => {
    if (!p || typeof p !== 'object' || Array.isArray(p)) {
      throw new PagesFileError(`${cfgPath}: pages[${i}] must be an object such as {"name": "home", "path": "/"}`);
    }
    if (typeof p.name !== 'string' || !p.name) throw new PagesFileError(`${cfgPath}: pages[${i}] needs a "name" (a short word used in file names)`);
    if (typeof p.path !== 'string') throw new PagesFileError(`${cfgPath}: pages[${i}] needs a "path" string such as "/" or "/pricing" (page "${p.name}")`);
  });
  if (!envBase && !cfg.base) {
    if (cfg.bareList) {
      throw new PagesFileError(`${cfgPath}: needs a "base": a bare list of pages works only through with_server.py (which sets PROOFS_BASE_URL); otherwise write ${shape}`);
    }
    throw new PagesFileError(`${cfgPath}: needs a "base" such as "http://localhost:3000" (or run through with_server.py, which sets PROOFS_BASE_URL)`);
  }
  return cfg;
}

// Runs in the page: its title and first heading, when they read like an error page and
// nothing else ("404", "Not Found", "500 Internal Server Error", "Error: 404").
function errorPageText() {
  const words = /^(?:error\s*)?(?:[:\-|–—]\s*)?(?:(?:40[0-9]|50[0-9])\s*)?(?:[:\-|–—]\s*)?(?:page\s+)?(?:not\s+found|internal\s+server\s+error|server\s+error|bad\s+request|forbidden|unauthorized|service\s+unavailable|bad\s+gateway)?$/i;
  const code = /^(?:error\s*)?(?:[:\-|–—]\s*)?(?:40[0-9]|50[0-9])\b/i;
  const plain = (t) => (t || '').replace(/\s+/g, ' ').trim();
  const looks = (t) => t && t.length <= 60 && (words.test(t) && /[a-z0-9]/i.test(t))
    && (code.test(t) || /not\s+found|server\s+error|bad\s+request|forbidden|unauthorized|unavailable|bad\s+gateway/i.test(t));
  const title = plain(document.title);
  const h1 = document.querySelector('h1');
  const head = plain(h1 && h1.innerText);
  if (looks(title)) return title;
  if (looks(head)) return head;
  return null;
}

class PageFailed extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

// Scrolling. 400 px steps are under half the shortest viewport (844), so every part of the page
// spends at least one step inside the screen; two animation frames and then 250 ms let an
// IntersectionObserver fire and a lazy image start loading (on the AstroWind page in dev mode,
// 100 ms left 1 to 38 blocks unrevealed from run to run, 200 ms none in three runs); 1 s after the return to the top lets a fade-in finish (AstroWind's
// takes 0.6 s); images still loading get up to 5 s more. 150 steps (60,000 px) caps a page
// that keeps growing as it scrolls.
const SCROLL = { step: 400, pause: 250, settle: 1000, imageWait: 5000, maxSteps: 150 };

// Runs in the page: scroll to the bottom in steps, back to the top, and wait.
async function scrollThrough({ step, pause, settle, imageWait, maxSteps }) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let y = 0;
  for (let n = 0; n < maxSteps; n++) {
    const bottom = document.documentElement.scrollHeight - window.innerHeight;
    if (y >= bottom) break;
    y = Math.min(y + step, bottom);
    window.scrollTo(0, y);
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    await sleep(pause);
  }
  window.scrollTo(0, 0);
  const pending = [...document.images].filter((i) => !i.complete)
    .map((i) => new Promise((r) => { i.addEventListener('load', r, { once: true }); i.addEventListener('error', r, { once: true }); }));
  await Promise.race([Promise.all(pending), sleep(imageWait)]);
  await sleep(settle);
}

// Runs in the page. Returns raw numbers; pass/fail is decided in Node.
// `edge`, when given, is the screen's width to measure overflow against (the plain
// recheck of a phone layout that came out wider than the screen).
function measure({ items, minText, minTap, edge, offCenterPx = 16, untitledMinHeight = 120 }) {
  const vw = edge || document.documentElement.clientWidth;
  const vh = window.innerHeight;
  const visible = (el) => {
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1) return false;
    // Off-page (skip links, visually-hidden text) is not something a person sees
    if (r.right < 0 || r.bottom < -window.scrollY || r.left > document.documentElement.scrollWidth) return false;
    return !el.closest('.sr-only,.visually-hidden,[aria-hidden=true]');
  };
  const label = (el) => {
    const t = (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().replace(/\s+/g, ' ');
    return t.slice(0, 40);
  };

  // Sideways scroll. scrollWidth alone misses content that `overflow-x: hidden` clips, so also
  // take the right edge of the widest visible element. Not counted: an element that starts at or
  // past the screen edge (a closed drawer), one inside an auto/scroll box (a carousel the person
  // can swipe), and one entirely past a hidden/clip ancestor's right edge (a cut-off slide). A
  // partly visible element in a clipping wrapper still counts: that is the bug.
  const scrollWidth = document.documentElement.scrollWidth;
  const sideways = scrollWidth - vw;
  const skippedByAncestor = (el, r) => {
    for (let a = el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      const ox = getComputedStyle(a).overflowX;
      if (ox === 'visible') continue;
      const ar = a.getBoundingClientRect();
      if ((ox === 'auto' || ox === 'scroll') && r.right > ar.right + 1) return true;
      if ((ox === 'hidden' || ox === 'clip') && r.left >= ar.right - 1) return true;
    }
    return false;
  };
  let widestRight = 0;
  const overflowing = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.left >= vw - 1 || skippedByAncestor(el, r)) continue;
    widestRight = Math.max(widestRight, r.right);
    if (r.right > vw + 1) overflowing.push({ text: label(el), tag: el.tagName.toLowerCase(), past: Math.round(r.right - vw) });
  }
  overflowing.sort((x, y) => y.past - x.past);

  // Main column width
  const main = document.querySelector('main') || document.body;
  const mainBox = main.getBoundingClientRect();
  let contentLeft = Infinity, contentRight = 0;
  for (const el of main.querySelectorAll('h1,h2,h3,p,li,table,img,form,article,section > *')) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 40) continue;
    contentLeft = Math.min(contentLeft, r.left);
    contentRight = Math.max(contentRight, r.right);
  }
  const contentWidth = contentRight > contentLeft ? contentRight - contentLeft : mainBox.width;

  // Text smaller than the floor (SVG text measured in rendered pixels)
  const smallText = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent.trim()) continue;
    const el = node.parentElement;
    if (!el || seen.has(el) || !visible(el)) continue;
    seen.add(el);
    let px = parseFloat(getComputedStyle(el).fontSize);
    if (el instanceof SVGElement && el.getScreenCTM) {
      const m = el.getScreenCTM();
      if (m) px = px * Math.hypot(m.a, m.b);
    }
    if (px < minText - 0.5) smallText.push({ text: node.textContent.trim().slice(0, 40), px: +px.toFixed(1),
      y: Math.round(el.getBoundingClientRect().top + window.scrollY) });
  }

  // Tap targets (a stretched ::after covering the row counts as the row)
  const smallTaps = [];
  for (const el of document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button]')) {
    if (!visible(el) || el.tabIndex === -1) continue;
    let r = el.getBoundingClientRect();
    const after = getComputedStyle(el, '::after');
    if (after.content !== 'none' && after.position === 'absolute' && after.inset === '0px') {
      const holder = el.closest('[style*=relative], li, tr, article, .card') || el.parentElement;
      if (holder) r = holder.getBoundingClientRect();
    }
    const inline = getComputedStyle(el).display === 'inline' && el.closest('p,li');
    if (inline) continue; // links inside running text are exempt
    if (r.width < minTap - 0.5 || r.height < minTap - 0.5) {
      smallTaps.push({ el: label(el), tag: el.tagName.toLowerCase(), w: Math.round(r.width), h: Math.round(r.height),
        y: Math.round(r.top + window.scrollY) });
    }
  }

  // Truncation while there is room beside it
  const truncated = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.children.length > 3) continue;
    const s = getComputedStyle(el);
    const clipped = (s.textOverflow === 'ellipsis' && el.scrollWidth > el.clientWidth + 1) ||
      (s.webkitLineClamp !== 'none' && s.webkitLineClamp && el.scrollHeight > el.clientHeight + 1);
    if (!clipped) continue;
    const parent = el.parentElement.getBoundingClientRect();
    const room = parent.right - el.getBoundingClientRect().right;
    truncated.push({ text: label(el), roomPx: Math.round(room) });
  }

  // Rows that should be centered and are not. `text-align: center` centers text and inline
  // boxes, but not a flex or grid container's items, nor a block child narrower than its
  // parent. Angular run 1: a footer column centered at 390, its "Events" link made
  // `display: flex` for a badge, sat at the left, and no measure or look caught it. For each
  // box whose text-align is center, take its in-flow children's extent (elements and text)
  // inside its content box; a gap on one side larger than the other by more than offCenterPx
  // is a finding. A full-width child (block text, a space-between row) leaves no gaps.
  const offCenter = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el instanceof SVGElement || !visible(el)) continue;
    const s = getComputedStyle(el);
    if (s.textAlign !== 'center' || s.display === 'inline' || s.display === 'contents') continue;
    let cl = Infinity, cr = -Infinity;
    for (const node of el.childNodes) {
      let rects = [];
      if (node.nodeType === Node.TEXT_NODE) {
        if (!node.textContent.trim()) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        rects = [...range.getClientRects()];
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const cs = getComputedStyle(node);
        if (cs.position === 'absolute' || cs.position === 'fixed' || cs.float !== 'none' || !visible(node)) continue;
        rects = [node.getBoundingClientRect()];
      }
      for (const r of rects) {
        if (r.width <= 0) continue;
        cl = Math.min(cl, r.left);
        cr = Math.max(cr, r.right);
      }
    }
    if (cl === Infinity) continue;
    const box = el.getBoundingClientRect();
    const left = cl - (box.left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft));
    const right = (box.right - parseFloat(s.borderRightWidth) - parseFloat(s.paddingRight)) - cr;
    if (left < -1 || right < -1) continue; // overflowing content is the sideways measure's job
    if (Math.abs(left - right) > offCenterPx) {
      offCenter.push({ text: label(el), tag: el.tagName.toLowerCase(), left: Math.round(left), right: Math.round(right),
        y: Math.round(box.top + window.scrollY) });
    }
  }

  // Blocks still at opacity 0 after the scroll (a reveal-on-scroll section that never
  // revealed): in flow, at least 24x24 px, holding text or an image. Absolutely placed ones
  // are hover overlays and icon swaps, not content. Only the outermost of a nested set counts.
  const hiddenEls = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el instanceof SVGElement) continue;
    const s = getComputedStyle(el);
    if (+s.opacity !== 0 || s.display === 'none' || s.visibility === 'hidden') continue;
    if (s.position === 'absolute' || s.position === 'fixed') continue;
    if (hiddenEls.some((h) => h.contains(el))) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) continue;
    if (el.closest('.sr-only,.visually-hidden,[aria-hidden=true]')) continue;
    if (!(el.innerText || '').trim() && !el.querySelector('img,svg,video,canvas,picture')) continue;
    hiddenEls.push(el);
  }
  const hiddenBlocks = hiddenEls.map((el) => ({ text: label(el), tag: el.tagName.toLowerCase() }));

  // Page columns: a box with a max-width in px, in normal flow, whose parent spans the page
  // (at least 90% of it) and which is at least half the page wide: a section's container.
  // Two ways one is out of line (Astro run 1: the steps section's max-w-5xl column, centered
  // but with left-aligned content, began 128 px right of the blocks above and below it):
  // - "column": it is narrower than its parent and not centered in it (gaps differ by more
  //   than offCenterPx);
  // - "edge": its content hugs its left edge, and that edge is more than offCenterPx from the
  //   left edge of the columns above and below it, which agree with each other.
  const cols = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el instanceof SVGElement || !visible(el)) continue;
    const s = getComputedStyle(el);
    if (!/px$/.test(s.maxWidth)) continue;
    if (s.position === 'absolute' || s.position === 'fixed' || s.float !== 'none') continue;
    const parent = el.parentElement;
    if (!parent || cols.some((c) => c.el.contains(el))) continue;
    const ps = getComputedStyle(parent);
    if (ps.display.includes('grid') || (ps.display.includes('flex') && !ps.flexDirection.startsWith('column'))) continue;
    const pr = parent.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (pr.width < vw * 0.9 || r.width < vw * 0.5) continue;
    cols.push({ el, r, s, pr, ps, edge: r.left + parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft) });
  }
  const textLeft = (el) => {
    let left = Infinity;
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const n = tw.currentNode;
      if (!n.textContent.trim() || !n.parentElement || !visible(n.parentElement)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const b of range.getClientRects()) if (b.width > 0) left = Math.min(left, b.left);
    }
    return left;
  };
  const offColumns = [];
  cols.forEach((c, i) => {
    const contentLeft = c.pr.left + parseFloat(c.ps.borderLeftWidth) + parseFloat(c.ps.paddingLeft);
    const contentRight = c.pr.right - parseFloat(c.ps.borderRightWidth) - parseFloat(c.ps.paddingRight);
    const left = c.r.left - contentLeft, right = contentRight - c.r.right;
    if (left > 1 || right > 1) {
      if (left >= -1 && right >= -1 && Math.abs(left - right) > offCenterPx) {
        offColumns.push({ kind: 'column', text: label(c.el), tag: c.el.tagName.toLowerCase(), left: Math.round(left), right: Math.round(right) });
        return;
      }
    }
    const prev = cols[i - 1], next = cols[i + 1];
    if (!prev || !next || Math.abs(prev.edge - next.edge) > offCenterPx) return;
    if (Math.abs(c.edge - prev.edge) <= offCenterPx) return;
    if (Math.abs(textLeft(c.el) - c.edge) > offCenterPx) return; // centered content: deliberate
    offColumns.push({ kind: 'edge', text: label(c.el), tag: c.el.tagName.toLowerCase(),
      edge: Math.round(c.edge), neighbors: Math.round((prev.edge + next.edge) / 2) });
  });

  // Sections without a heading (Astro run 2: AstroWind's proof strip and stats band). A
  // `section`, `article`, `aside` or `role="region"` block, the outermost of a nested set, at
  // least untitledMinHeight tall and half the page wide, holding visible text, with no h1-h6
  // or role="heading" inside: a reader scanning by headings (or a screen reader's heading list)
  // skips it. A note, not a failure: some bands are deliberately unheaded.
  const blockSel = 'section, article, aside, [role=region]';
  const untitled = [];
  for (const el of document.querySelectorAll(blockSel)) {
    if (!visible(el)) continue;
    if (el.parentElement && el.parentElement.closest(blockSel)) continue;
    const r = el.getBoundingClientRect();
    if (r.height < untitledMinHeight || r.width < vw * 0.5) continue;
    if (!(el.innerText || '').trim()) continue;
    if (el.querySelector('h1,h2,h3,h4,h5,h6,[role=heading]')) continue;
    untitled.push({ text: label(el), tag: el.tagName.toLowerCase(), id: el.id || '',
      top: Math.round(r.top + window.scrollY), height: Math.round(r.height) });
  }

  // Repeated items: how many fit the first screen, how tall, where the first starts
  let itemStats = null;
  if (items) {
    const els = [...document.querySelectorAll(items)].filter(visible);
    const boxes = els.map((e) => e.getBoundingClientRect());
    const hs = boxes.map((b) => b.height).sort((a, b) => a - b);
    const rows = new Set(boxes.filter((b) => b.top >= 0 && b.bottom <= vh).map((b) => Math.round(b.top)));
    itemStats = {
      total: els.length,
      fullyVisible: boxes.filter((b) => b.top >= 0 && b.bottom <= vh).length,
      rowsVisible: rows.size,
      medianHeight: hs.length ? Math.round(hs[Math.floor(hs.length / 2)]) : null,
      firstItemY: boxes.length ? Math.round(boxes[0].top) : null,
      chromeShare: boxes.length ? +(boxes[0].top / vh).toFixed(2) : null,
    };
  }

  // Section inventory, for the designer: each section's label and position and the elements in
  // it, in DOM order. A section is a landmark or a direct child of <main>, deduped to the
  // outermost. `main > *` has no height floor on purpose: whatever the author put directly in
  // <main> is a section. Landmarks that cover under SECTION_MIN_COVER of the page's height (a
  // lone <header> over a div soup, or no landmarks at all) are topped up with the direct children
  // of <main> (else <body>) at least SECTION_MIN_HEIGHT tall that are not already inside a
  // section: anything shorter is a bar or a divider, not a section. If that still leaves nothing
  // (a short page), the whole <main> (else <body>) is the one section, so the list is never empty.
  // Caps keep measures.json small: 30 sections, 40 elements each.
  const SECTION_MIN_HEIGHT = 200, SECTION_MIN_COVER = 0.5, MAX_SECTIONS = 30, MAX_ELEMENTS = 40, TEXT_CAP = 80;
  const clip = (t) => (t || '').trim().replace(/\s+/g, ' ').slice(0, TEXT_CAP);
  const pageTop = (r) => Math.round(r.top + window.scrollY);
  let sectionEls = [...document.querySelectorAll(
    'section, header, footer, main > *, [role=region], [role=banner], [role=contentinfo]')].filter(visible);
  sectionEls = sectionEls.filter((el) => !sectionEls.some((o) => o !== el && o.contains(el)));
  const covered = sectionEls.reduce((sum, el) => sum + el.getBoundingClientRect().height, 0);
  if (covered < SECTION_MIN_COVER * document.documentElement.scrollHeight) {
    const root = document.querySelector('main') || document.body;
    const extra = [...root.children].filter((el) => visible(el)
      && el.getBoundingClientRect().height > SECTION_MIN_HEIGHT
      && !sectionEls.some((o) => o === el || o.contains(el)));
    sectionEls = [...sectionEls, ...extra].sort((x, y) => (x.compareDocumentPosition(y) & 4 ? -1 : 1));
  }
  if (!sectionEls.length) sectionEls = [document.querySelector('main') || document.body];
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
  const sections = sectionEls.slice(0, MAX_SECTIONS).map((sec, i) => {
    const sr = sec.getBoundingClientRect();
    const heading = sec.querySelector('h1,h2,h3,h4,h5,h6,[role=heading]');
    const headingText = heading ? clip(heading.innerText) : '';
    const className = typeof sec.className === 'string' ? sec.className.trim().split(/\s+/)[0] : '';
    const taken = new Set();
    const elements = [];
    // `layout` is the near-copy signature's view of the same elements (see "Layout boxes"
    // above) plus the section's pictures, page px; `elements` keeps the block boxes.
    const layout = [];
    const place = (kind, r) => ({ kind, top: pageTop(r), left: Math.round(r.left),
      width: Math.round(r.width), height: Math.round(r.height) });
    for (const el of sec.querySelectorAll(elementSel)) {
      if (elements.length >= MAX_ELEMENTS) break;
      if (!visible(el)) continue;
      let inside = false;
      for (let a = el.parentElement; a && a !== sec; a = a.parentElement) if (taken.has(a)) { inside = true; break; }
      if (inside) continue;
      const kind = kindOf(el);
      if (holds.has(kind)) taken.add(el);
      const r = el.getBoundingClientRect();
      const text = kind === 'image' ? clip(el.getAttribute('alt')) : clip(el.innerText || el.value);
      elements.push({ kind, text, tag: el.tagName.toLowerCase(), top: pageTop(r),
        left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) });
      layout.push(place(kind, layoutRect(el, kind)));
    }
    for (const el of pictureEls(sec, taken, 0.02 * sr.width * sr.height)) {
      if (layout.length >= MAX_ELEMENTS) break;
      layout.push(place('image', el.getBoundingClientRect()));
    }
    return { id: sec.id || '', tag: sec.tagName.toLowerCase(),
      label: headingText || sec.id || className || `section ${i + 1}`,
      top: pageTop(sr), height: Math.round(sr.height),
      left: Math.round(sr.left), width: Math.round(sr.width), elements, layout };
  });

  // Distinct computed text sizes (px) of the visible elements that hold text of their own.
  const sizeSet = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (![...el.childNodes].some((n) => n.nodeType === 3 && n.nodeValue.trim())) continue;
    if (!visible(el)) continue;
    sizeSet.add(+parseFloat(getComputedStyle(el).fontSize).toFixed(2));
  }
  const fontSizes = [...sizeSet].filter((n) => n > 0).sort((a, b) => a - b);

  return {
    viewport: { w: vw, h: vh },
    innerWidth: window.innerWidth, dpr: window.devicePixelRatio,
    scrollWidth, clientWidth: vw, widestRight: Math.round(widestRight), overflowing: overflowing.slice(0, 5),
    pageHeight: document.documentElement.scrollHeight,
    sideways,
    contentWidth: Math.round(contentWidth),
    contentShare: +(contentWidth / vw).toFixed(2),
    smallText: smallText.slice(0, 25), smallTextCount: smallText.length,
    smallTaps: smallTaps.slice(0, 25), smallTapCount: smallTaps.length,
    truncated: truncated.slice(0, 15),
    offCenter: offCenter.slice(0, 15), offCenterCount: offCenter.length,
    offColumns: offColumns.slice(0, 15), offColumnCount: offColumns.length,
    hiddenBlocks: hiddenBlocks.length, hiddenList: hiddenBlocks.slice(0, 5),
    untitled: untitled.slice(0, 15), untitledCount: untitled.length,
    items: itemStats,
    sections, fontSizes,
  };
}

// Width of a PNG from its IHDR chunk (bytes 16-19, big-endian).
function pngWidth(file) {
  const fd = fs.openSync(file, 'r');
  const b = Buffer.alloc(24);
  fs.readSync(fd, b, 0, 24, 0);
  fs.closeSync(fd);
  return b.readUInt32BE(16);
}

// Below the first screen of a full-page PNG: the share of pixel rows with no detail (no step
// between neighboring pixels over FLAT_STEP in any channel) and the share of pixels in the most
// common color (channels rounded to 16 levels). Both at BLANK_SHARE or more, over at least one
// screen's height, is a blank region: a solid-color section is flat but a second color, and a
// page of text has one color but few flat rows. Null when the PNG is not 8-bit RGB or RGBA.
const FLAT_STEP = 12;
const BLANK_SHARE = 0.9;
// Blocks still at opacity 0 after the scroll that make a page "hidden": one or two can be a
// deliberate icon or toggle; three or more is content that never appeared.
const HIDDEN_BLOCKS = 3;

// The rows of an 8-bit, non-interlaced RGB or RGBA PNG (what Chrome writes), unfiltered; null
// for any other kind.
function decodePng(file) {
  const zlib = require('zlib');
  const data = fs.readFileSync(file);
  let pos = 8, width = 0, height = 0, depth = 0, ctype = 0, interlace = 0;
  const idat = [];
  while (pos < data.length) {
    const len = data.readUInt32BE(pos);
    const kind = data.toString('latin1', pos + 4, pos + 8);
    if (kind === 'IHDR') {
      width = data.readUInt32BE(pos + 8); height = data.readUInt32BE(pos + 12);
      depth = data[pos + 16]; ctype = data[pos + 17]; interlace = data[pos + 20];
    } else if (kind === 'IDAT') idat.push(data.subarray(pos + 8, pos + 8 + len));
    pos += 12 + len;
  }
  if (depth !== 8 || (ctype !== 2 && ctype !== 6) || interlace) return null;
  const bpp = ctype === 6 ? 4 : 3, stride = width * bpp;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const rows = [];
  let prev = Buffer.alloc(stride);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const line = Buffer.from(raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      if (f === 1) line[i] = (line[i] + a) & 255;
      else if (f === 2) line[i] = (line[i] + b) & 255;
      else if (f === 3) line[i] = (line[i] + ((a + b) >> 1)) & 255;
      else if (f === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        line[i] = (line[i] + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255;
      }
    }
    rows.push(line);
    prev = line;
  }
  return { width, height, bpp, ctype, rows };
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = CRC_TABLE[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function writePng(file, width, height, bpp, rows) {
  const zlib = require('zlib');
  const chunk = (kind, body) => {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(body.length, 0);
    head.write(kind, 4, 'latin1');
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])), 0);
    return Buffer.concat([head, body, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = bpp === 4 ? 6 : 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const raw = Buffer.concat(rows.map((r) => Buffer.concat([Buffer.from([0]), r])));
  fs.writeFileSync(file, Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]));
}

// Cuts the CSS-px rows [top, bottom) out of a decoded full-page shot taken at `scale` device
// pixels per CSS px and writes them at one PNG px per CSS px (each scale x scale block averaged).
// Cropping the full shot, rather than taking a second screenshot of a region, keeps every part
// identical to it: a clipped screenshot re-lays out the page, and a sticky header then lands on
// top of the content (AstroWind's header covered its own hero headline).
function writePart(png, scale, top, bottom, file) {
  const s = Math.max(1, Math.round(scale));
  const width = Math.floor(png.width / s);
  const rows = [];
  for (let y = top; y < bottom; y++) {
    const line = Buffer.alloc(width * png.bpp);
    for (let x = 0; x < width; x++) {
      for (let ch = 0; ch < png.bpp; ch++) {
        let sum = 0, n = 0;
        for (let dy = 0; dy < s; dy++) {
          const src = png.rows[y * s + dy];
          if (!src) continue;
          for (let dx = 0; dx < s; dx++) { sum += src[((x * s) + dx) * png.bpp + ch]; n++; }
        }
        line[x * png.bpp + ch] = n ? Math.round(sum / n) : 0;
      }
    }
    rows.push(line);
  }
  writePng(file, width, rows.length, png.bpp, rows);
}

function regionStats(file, dpr, fromCss) {
  const png = decodePng(file);
  if (!png) return null;
  const { width, height, bpp, rows: lines } = png;
  const stride = width * bpp;
  const start = Math.min(height, Math.round(fromCss * dpr));
  let flatRows = 0, rows = 0, sampled = 0;
  const colors = new Map();
  for (let y = start; y < height; y++) {
    const line = lines[y];
    rows++;
    let flat = true;
    for (let i = bpp; i < stride && flat; i++) {
      if (bpp === 4 && i % 4 === 3) continue;
      if (Math.abs(line[i] - line[i - bpp]) > FLAT_STEP) flat = false;
    }
    if (flat) flatRows++;
    for (let x = 0; x < width; x += 4) {
      const k = ((line[x * bpp] >> 4) << 8) | ((line[x * bpp + 1] >> 4) << 4) | (line[x * bpp + 2] >> 4);
      colors.set(k, (colors.get(k) || 0) + 1);
      sampled++;
    }
  }
  const top = Math.max(0, ...colors.values());
  return { rows, flatShare: rows ? +(flatRows / rows).toFixed(2) : 0, colorShare: sampled ? +(top / sampled).toFixed(2) : 0 };
}

// m.blank: whether the shot shows the page, from the PNG and the opacity-0 count.
function blankOf(m, file) {
  const vh = m.viewport.h;
  let st = null;
  const scale = m.fullScale || m.dpr || 1;
  try { st = regionStats(file, scale, vh); } catch (_) { st = null; }
  const regionPx = st ? Math.round(st.rows / scale) : 0;
  const image = !!st && regionPx >= vh && st.flatShare >= BLANK_SHARE && st.colorShare >= BLANK_SHARE;
  const hidden = m.hiddenBlocks >= HIDDEN_BLOCKS;
  m.blank = { flagged: image || hidden, image, hidden, regionPx,
    flatShare: st ? st.flatShare : null, colorShare: st ? st.colorShare : null, hiddenBlocks: m.hiddenBlocks };
}

function blankText(b) {
  const parts = [];
  if (b.image) parts.push(`${Math.round(b.colorShare * 100)}% one flat color below the first screen`);
  if (b.hidden) parts.push(`${b.hiddenBlocks} blocks at opacity 0`);
  return parts.join(', ');
}

// Folds the overflow signals into m.sideways (the worst of them) and m.signals. A phone
// layout that came out wider than the screen (m.zoomedOut) is measured against the screen.
function overflowOf(m) {
  const z = m.zoomedOut;
  const cw = z ? z.screenWidth : m.clientWidth;
  const scroll = (z ? z.layoutWidth : m.scrollWidth) - cw;
  const clipped = m.widestRight - cw;
  const image = Math.round(m.pngWidth / (m.fullScale || m.dpr)) - cw;
  const signals = [];
  if (z) signals.push('zoomed');
  else if (scroll > 1) signals.push('scroll');
  else if (clipped > 1) signals.push('clipped');
  if (image > 1 && !z) signals.push('image');
  m.signals = signals;
  m.sideways = Math.max(scroll, clipped, image, 0);
}

// Goes to the page and runs its actions (shared by the capture and the plain recheck).
// The site's own logo, for a design review that cannot find the logo file in the project. In the
// header (else the first section), the first visible: (1) element whose id, class or alt says
// "logo"; (2) img, svg or picture inside the header's link to "/"; (3) that link itself; (4) img,
// svg or picture. Tiers, not document order, because many headers open with a menu or search
// icon before the logo, and a single pass cropped that icon. Marks it with
// data-proofs-logo so the caller can take an element screenshot, and returns its page box and
// a "tag#id.class" source, or null when there is none.
function findLogo() {
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0;
  };
  const header = document.querySelector('header, [role="banner"]');
  const root = header || document.querySelector('main > section, section, main > *');
  if (!root) return null;
  const named = (el) => /logo/i.test([el.id, el.getAttribute('class'), el.getAttribute('alt')].filter(Boolean).join(' '));
  const all = [...root.querySelectorAll('*')].filter(seen);
  const picture = (e) => ['img', 'svg', 'picture'].includes(e.localName);
  const home = header ? [...header.querySelectorAll('a[href]')].find((a) => {
    if (!seen(a)) return false;
    try { const u = new URL(a.href); return u.origin === location.origin && u.pathname === '/'; } catch { return false; }
  }) : null;
  const el = all.find(named)
    || (home && [...home.querySelectorAll('img, svg, picture')].find(seen))
    || home
    || all.find(picture);
  if (!el) return null;
  document.querySelectorAll('[data-proofs-logo]').forEach((x) => x.removeAttribute('data-proofs-logo'));
  el.setAttribute('data-proofs-logo', '');
  const r = el.getBoundingClientRect();
  const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean);
  return {
    box: { left: Math.round(r.left + window.scrollX), top: Math.round(r.top + window.scrollY),
      width: Math.round(r.width), height: Math.round(r.height) },
    source: el.localName + (el.id ? `#${el.id}` : '') + cls.map((c) => `.${c}`).join(''),
  };
}

async function openPage(page, base, p, scroll = true) {
  const url = joinUrl(base, p.path);
  const response = await page.goto(url, { waitUntil: 'networkidle' });
  const status = response && typeof response.status === 'function' ? response.status() : null;
  if (status && status >= 400) {
    throw new PageFailed(`${url} answered HTTP ${status}; this is not the page. Check "base" and "path" in the pages file and the server log`, status);
  }
  const looks = await page.evaluate(errorPageText);
  if (typeof looks === 'string' && looks) {
    throw new PageFailed(`${url} looks like an error page ("${looks}"); this is not the page. Check "base" and "path" in the pages file and the server log`, status);
  }
  for (const a of p.actions || []) {
    if (a.click) await page.click(a.click);
    if (a.waitFor) await page.waitForSelector(a.waitFor);
    if (a.eval) await page.evaluate(a.eval);
  }
  await page.evaluate(() => document.fonts && document.fonts.ready);
  if (scroll) await page.evaluate(scrollThrough, SCROLL);
}

// An emulated phone lays the page out wider than its screen when the content is too wide,
// as a real phone zooms out to fit (Rails run 1: 407 px at 390). A browser that ignores the
// viewport (headless Chrome on macOS once had a minimum width) is wide in a plain desktop
// context too. So load the page once more at the same width without phone emulation: if
// that context is the asked width and the content runs past it, the overflow is the page's.
async function recheckWide(browser, vp, base, p, setup, minText, minTap, scroll) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  try {
    const page = await context.newPage();
    if (setup) await setup(page, base);
    await openPage(page, base, p, scroll);
    const flat = await page.evaluate(measure, { items: p.items, minText, minTap, edge: vp.width });
    const real = flat && flat.innerWidth === vp.width
      && Math.max(flat.scrollWidth || 0, flat.widestRight || 0) > vp.width + 1;
    return real ? flat : null;
  } finally {
    await context.close();
  }
}

// Parts: at most PART_ASPECT widths tall and PART_MAX_PX px, so a reader that shrinks an image
// to fit about 1,568 px on its long side still shows text at a readable size. FULL_MAX_PX is
// the tallest full-page PNG taken at the device scale; past it the shot is taken at 1x.
const PART_MAX_PX = 1600;
const PART_ASPECT = 4;
const FULL_MAX_PX = 16384;

function partRanges(pageHeight, width) {
  const h = Math.min(PART_MAX_PX, PART_ASPECT * width);
  if (!(pageHeight > h)) return [];
  const out = [];
  for (let top = 0; top < pageHeight; top += h) out.push({ top, bottom: Math.min(pageHeight, top + h) });
  return out;
}

function partOf(parts, y) {
  const p = parts.find((x) => y >= x.top && y < x.bottom);
  return p ? p.file : null;
}

// Entries in `now` that the earlier list does not have as many times, by key.
function freshEntries(before, now, key) {
  const left = new Map();
  for (const e of before || []) left.set(key(e), (left.get(key(e)) || 0) + 1);
  const out = [];
  for (const e of now || []) {
    const k = key(e), n = left.get(k) || 0;
    if (n > 0) left.set(k, n - 1); else out.push(e);
  }
  return out;
}

const COMPARED = [
  ['smallTaps', 'small tap targets', (t) => `${t.tag}|${t.el}`, (t) => `"${t.el}" ${t.w}x${t.h}px at y ${t.y}`, 'smallTapCount'],
  ['smallText', 'text below floor', (t) => t.text, (t) => `"${t.text}" ${t.px}px at y ${t.y}`, 'smallTextCount'],
  ['midWord', 'mid-word breaks', (w) => w, (w) => `"${w}"`, null],
  ['offCenter', 'off-center rows', (o) => `${o.tag}|${o.text}`, (o) => `"${o.text || o.tag}" ${o.left}px/${o.right}px`, 'offCenterCount'],
  ['offColumns', 'off-center columns', (o) => `${o.tag}|${o.text}`, (o) => `"${o.text || o.tag}"`, 'offColumnCount'],
  ['overflowing', 'wider than the screen', (o) => `${o.tag}|${o.text}`, (o) => `"${o.text || o.tag}" ${o.past}px past`, null],
];

function newSince(old, m) {
  const out = { cut: [] };
  for (const [field, name, key, , count] of COMPARED) {
    out[field] = freshEntries(old[field], m[field], key);
    if (count && (old[count] > (old[field] || []).length || m[count] > (m[field] || []).length)) out.cut.push(name);
  }
  return out;
}

function verdicts(m, vpLabel) {
  const phone = vpLabel === '390';
  const out = [];
  out.push(['sideways scroll', m.signals.length ? `${m.sideways}px, ${m.signals.join('+')}` : m.sideways,
    m.sideways <= 1]);
  if (!phone) out.push(['content width share', m.contentShare, m.contentShare >= 0.7]);
  out.push(['text below floor', m.smallTextCount, m.smallTextCount === 0]);
  out.push(['small tap targets', m.smallTapCount, m.smallTapCount === 0]);
  out.push(['truncated with room', m.truncated.filter((t) => t.roomPx > 24).length,
    m.truncated.every((t) => t.roomPx <= 24)]);
  out.push(['mid-word breaks', m.midWord.length, m.midWord.length === 0]);
  out.push(['off-center rows', m.offCenterCount, m.offCenterCount === 0]);
  out.push(['off-center columns', m.offColumnCount, m.offColumnCount === 0]);
  out.push(['blank or hidden content', m.blank.flagged ? blankText(m.blank) : 'no', !m.blank.flagged]);
  // A note (null), not a failed check: listed only when there is one.
  if (m.untitledCount) out.push(['sections without headings', m.untitledCount, null]);
  if (m.items) {
    out.push(['chrome before first item', m.items.chromeShare, m.items.chromeShare < 0.4]);
    out.push(['items in first screen', m.items.fullyVisible, null]);
    out.push(['median item height', m.items.medianHeight, null]);
  }
  return out;
}

async function main() {
  const argv = process.argv.slice(2);
  const opt = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
  const cfgPath = argv[0];
  if (!cfgPath || cfgPath.startsWith('--')) {
    console.error('usage: capture.cjs pages.json [--out DIR] [--sizes 390,1440] [--evidence before|after] [--no-scroll]');
    process.exit(1);
  }
  let cfg;
  try {
    cfg = readPagesFile(cfgPath, process.env.PROOFS_BASE_URL);
  } catch (e) {
    if (!(e instanceof PagesFileError)) throw e;
    console.error(e.message);
    process.exit(1);
  }
  const out = opt('--out') || path.join(path.dirname(cfgPath), 'shots');
  const evidence = opt('--evidence');
  const scroll = !argv.includes('--no-scroll');
  const comparePath = opt('--compare');
  let earlier = null;
  if (comparePath) {
    try {
      earlier = JSON.parse(fs.readFileSync(comparePath, 'utf8')).results || [];
    } catch (e) {
      console.error(`--compare ${comparePath}: cannot read an earlier measures.json (${e.code || String(e.message).split('\n')[0]})`);
      process.exit(1);
    }
  }
  const prefix = evidence ? `${evidence}-` : '';
  const sizes = opt('--sizes') ? opt('--sizes').split(',').map((x) => x.trim()) : null;
  const viewports = sizes ? pickViewports(sizes) : VIEWPORTS;
  if (!viewports.length) {
    console.error(`--sizes ${sizes.join(',')} matches none of ${VIEWPORTS.map((v) => v.label).join(', ')}, `
      + `or a desktop width from ${EXTRA_MIN} to ${EXTRA_MAX}`);
    process.exit(1);
  }
  const base = process.env.PROOFS_BASE_URL || cfg.base;
  fs.mkdirSync(out, { recursive: true });
  const outParts = path.resolve(out).split(path.sep);
  if (outParts.includes('.proofs')) {
    const proofsParent = outParts.slice(0, outParts.indexOf('.proofs')).join(path.sep) || path.sep;
    // Keep the scratch folder out of git via the clone's own exclude file; silent if git is missing.
    try {
      const cp = require('child_process');
      const run = (...a) => cp.execFileSync('git', a, { cwd: proofsParent, stdio: ['ignore', 'pipe', 'ignore'] }).toString();
      const ex = path.resolve(proofsParent, run('rev-parse', '--git-path', 'info/exclude').trim());
      let ignored = true;
      try { run('check-ignore', '-q', '.proofs/'); } catch (_) { ignored = false; }
      if (!ignored) {
        const cur = fs.existsSync(ex) ? fs.readFileSync(ex, 'utf8') : '';
        if (!cur.split('\n').some((l) => l.trim() === '.proofs/')) {
          fs.mkdirSync(path.dirname(ex), { recursive: true });
          fs.appendFileSync(ex, (cur && !cur.endsWith('\n') ? '\n' : '') + '.proofs/\n');
        }
      }
    } catch (_) { /* no git, not a repo, read-only: nothing to do */ }
  }
  const minText = cfg.minText || 16, minTap = cfg.minTap || 44;
  const setup = cfg.setup ? require(path.resolve(path.dirname(cfgPath), cfg.setup)) : null;

  const { chromium } = loadPlaywright();
  const browser = await launchChromium(chromium, process.env);
  const results = [];
  const errors = [];
  const failures = [];
  let untrusted = null;

  for (const vp of viewports) {
    if (untrusted) break;
    const { label, ...ctxOpts } = vp;
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, ...ctxOpts });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
    if (setup) await setup(page, base);

    for (const p of cfg.pages) {
      const state = p.state || 'default';
      const file = `${prefix}${p.name}-${state}-${label}`;
      const url = joinUrl(base, p.path);
      try {
        await openPage(page, base, p, scroll);
        await page.screenshot({ path: path.join(out, `${file}.png`) });
        const tall = await page.evaluate(() => document.documentElement.scrollHeight);
        const fullScale = tall * (vp.deviceScaleFactor || 1) > FULL_MAX_PX ? 1 : (vp.deviceScaleFactor || 1);
        await page.screenshot({ path: path.join(out, `${file}-full.png`), fullPage: true, ...(fullScale === 1 && vp.deviceScaleFactor > 1 ? { scale: 'css' } : {}) });
        const m = await page.evaluate(measure, { items: p.items, minText, minTap });
        m.fullScale = fullScale;
        m.parts = [];
        const ranges = m.innerWidth === vp.width ? partRanges(m.pageHeight, m.viewport.w) : [];
        const fullPng = ranges.length ? decodePng(path.join(out, `${file}-full.png`)) : null;
        if (fullPng) {
          // The shot's own height decides the last part's bottom (it can differ from scrollHeight by a px).
          const cssHeight = Math.floor(fullPng.height / fullScale);
          ranges.forEach((r, i) => {
            const bottom = i === ranges.length - 1 ? cssHeight : Math.min(r.bottom, cssHeight);
            if (r.top >= bottom) return;
            const name = `${file}-part-${String(i + 1).padStart(2, '0')}.png`;
            writePart(fullPng, fullScale, r.top, bottom, path.join(out, name));
            m.parts.push({ file: name, top: r.top, bottom });
          });
        }
        if (m.innerWidth !== vp.width) {
          const flat = vp.isMobile && m.innerWidth > vp.width
            ? await recheckWide(browser, vp, base, p, setup, minText, minTap, scroll) : null;
          if (!flat) {
            untrusted = `the browser laid the page out at ${m.innerWidth} px, not ${vp.width} px; the capture is not trustworthy`;
            break;
          }
          // The page is wider than the phone: a finding. Keep the phone's text and tap
          // numbers (taken at the zoomed-out width) and take the overflow from the recheck.
          m.zoomedOut = { layoutWidth: m.innerWidth, screenWidth: vp.width, past: m.innerWidth - vp.width };
          m.scrollWidth = Math.max(m.scrollWidth, m.innerWidth);
          m.clientWidth = vp.width;
          m.widestRight = flat.widestRight;
          m.overflowing = flat.overflowing;
        }
        // Additive (Task 6b): the logo crop design-review uses when the project has no logo file.
        const found = await page.evaluate(findLogo);
        m.logo = null;
        if (found && found.box) {
          const logoFile = `${prefix}${p.name}-${state === 'default' ? '' : `${state}-`}logo-${label}.png`;
          try {
            await page.locator('[data-proofs-logo]').first().screenshot({ path: path.join(out, logoFile) });
            m.logo = { file: logoFile, ...found };
          } catch (e) {
            m.logo = { file: null, ...found, error: e.message.split('\n')[0] };
          }
          await page.evaluate(() => document.querySelectorAll('[data-proofs-logo]').forEach((x) => x.removeAttribute('data-proofs-logo')));
        }
        const breaks = await page.evaluate(midWordBreaks, { selector: 'body', limit: 20 });
        m.midWord = breaks.map((w) => w.at);
        m.midWordAt = breaks.map((w) => ({ at: w.at, el: w.el, near: w.near, y: w.y, part: partOf(m.parts, w.y) }));
        m.pngWidth = pngWidth(path.join(out, `${file}-full.png`));
        overflowOf(m);
        blankOf(m, path.join(out, `${file}-full.png`));
        if (earlier) {
          const old = earlier.find((x) => x.page === p.name && x.state === state && x.viewport === label && x.measures);
          m.newSince = old ? newSince(old.measures, m) : null;
        }
        results.push({ page: p.name, state, viewport: label, file, url, measures: m, verdicts: verdicts(m, label) });
      } catch (e) {
        const error = e.message.split('\n')[0];
        if (e instanceof PageFailed) {
          failures.push({ page: p.name, state, viewport: label, path: p.path, url, status: e.status, error });
          results.push({ page: p.name, state, viewport: label, file, url, status: e.status, failed: true, error });
        } else {
          results.push({ page: p.name, state, viewport: label, file, url, error });
        }
      }
    }
    await context.close();
  }
  await browser.close();
  if (untrusted) { console.error(untrusted); process.exit(3); }

  fs.writeFileSync(path.join(out, `${prefix}measures.json`), JSON.stringify({ results, errors, failures }, null, 2));
  if (evidence) {
    const shots = results.filter((r) => !r.error).map((r) => ({
      label: r.viewport, size: r.viewport === '390' ? 'phone' : 'desktop',
      // 1440 and the phone are the page's default pair; any other width is its own page, labeled with the width.
      slug: `${r.page}-${r.state}${extraWidth(r.viewport) ? `-${r.viewport}` : ''}`,
      pageLabel: extraWidth(r.viewport) ? `${r.page} (${r.viewport})` : r.page,
      path: cfg.pages.find((p) => p.name === r.page && (p.state || 'default') === r.state).path,
      file: `${r.file}-full.png`,
      overflow: r.measures.sideways, overflowing: r.measures.overflowing,
      smallTargets: r.measures.smallTaps.map((t) => ({ text: t.el, tag: t.tag, width: t.w, height: t.h })), smallText: r.measures.smallText, smallTextCount: r.measures.smallTextCount,
      scrollWidth: r.measures.scrollWidth, clientWidth: r.measures.clientWidth,
      widestRight: r.measures.widestRight, pngWidth: r.measures.pngWidth, innerWidth: r.measures.innerWidth,
      offCenter: r.measures.offCenter, offCenterCount: r.measures.offCenterCount,
      offColumns: r.measures.offColumns, offColumnCount: r.measures.offColumnCount,
      blank: r.measures.blank, hiddenBlocks: r.measures.hiddenBlocks,
      untitled: r.measures.untitled, untitledCount: r.measures.untitledCount,
      midWord: r.measures.midWord, midWordAt: r.measures.midWordAt, parts: r.measures.parts,
      errors: errors.filter((e) => e.startsWith(`${r.viewport}:`)),
    }));
    fs.writeFileSync(path.join(out, `${evidence}.json`), JSON.stringify({ shots, failures }, null, 2));
  }
  const lines = ['| page | state | vp | fails | notes |', '|---|---|---|---|---|'];
  const seen = new Set();
  for (const r of results) {
    if (r.failed) { lines.push(`| ${r.page} | ${r.state} | ${r.viewport} | FAILED | ${r.error} |`); continue; }
    if (r.error) { lines.push(`| ${r.page} | ${r.state} | ${r.viewport} | ERROR | ${r.error} |`); continue; }
    const fails = r.verdicts.filter(([, , ok]) => ok === false).map(([k, v]) => `${k}: ${v}`);
    const info = r.verdicts.filter(([, , ok]) => ok === null).map(([k, v]) => `${k}: ${v}`);
    lines.push(`| ${r.page} | ${r.state} | ${r.viewport} | ${fails.join('; ') || 'none'} | ${info.join('; ')} |`);
    r.measures.signals.forEach((s) => seen.add(s));
  }
  const WORDS = {
    scroll: 'scroll: the page scrolls sideways.',
    clipped: 'clipped: content is wider than the screen but hidden by overflow-x, so it does not scroll and is cut off.',
    image: 'image: the full-page screenshot came out wider than the screen.',
    zoomed: 'zoomed: the page is wider than the phone screen, so the phone lays it out wider and zooms out to fit, '
      + 'shrinking everything; the other phone numbers were measured at that wider layout.',
  };
  if (seen.size) lines.push('', ...[...seen].map((s) => `- ${WORDS[s]}`));
  const offRows = results.filter((r) => !r.error && r.measures.offCenterCount);
  if (offRows.length) {
    lines.push('', 'off-center: a row inside a centered column (text-align: center) whose content sits to one side, '
      + 'usually a flex or grid row (text-align does not center its items; add justify-content: center) '
      + 'or a fixed-width block (add margin-inline: auto). Gaps are left/right of the content:');
    for (const r of offRows) {
      const rows = r.measures.offCenter.slice(0, 4).map((o) => `"${o.text || o.tag}" ${o.left}px/${o.right}px`);
      const more = r.measures.offCenterCount > 4 ? `; and ${r.measures.offCenterCount - 4} more` : '';
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${rows.join('; ')}${more}`);
    }
  }
  const offCols = results.filter((r) => !r.error && r.measures.offColumnCount);
  if (offCols.length) {
    lines.push('', 'off-center columns: a page-wide section column out of line. "not centered": it has a max-width '
      + 'and is not centered in its parent (add margin-inline: auto). "edge": its content starts at its left edge, and '
      + 'that edge is not where the columns above and below start (match their max-width, or center its content):');
    for (const r of offCols) {
      const cols = r.measures.offColumns.slice(0, 4).map((o) => (o.kind === 'column'
        ? `"${o.text || o.tag}" not centered, ${o.left}px/${o.right}px`
        : `"${o.text || o.tag}" edge at ${o.edge}px, the columns around it at ${o.neighbors}px`));
      const more = r.measures.offColumnCount > 4 ? `; and ${r.measures.offColumnCount - 4} more` : '';
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${cols.join('; ')}${more}`);
    }
  }
  const midRows = results.filter((r) => !r.error && r.measures.midWordAt.length);
  if (midRows.length) {
    lines.push('', 'mid-word breaks: a word the browser split across two lines. Where each one is (the element, '
      + 'the heading above it, its top in page px, and the part shot that shows it):');
    for (const r of midRows) {
      const spots = r.measures.midWordAt.slice(0, 6).map((w) => `"${w.at}" in ${w.el || '?'}`
        + `${w.near ? ` (under "${w.near}")` : ''}, y ${w.y}${w.part ? `, in ${w.part}` : ''}`);
      const more = r.measures.midWordAt.length > 6 ? `; and ${r.measures.midWordAt.length - 6} more` : '';
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${spots.join('; ')}${more}`);
    }
  }
  const partRows = results.filter((r) => !r.error && r.measures.parts.length);
  if (partRows.length) {
    lines.push('', 'parts: the page is too tall to read as one shot, so it is also saved in parts at 1x '
      + '(one PNG px per CSS px; each part\'s y range is in measures.json "parts"). Open the part a finding names, '
      + 'not the full shot, and use parts as the crops on a review page:');
    for (const r of partRows) {
      const ps = r.measures.parts;
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${ps.length} parts, ${ps[0].file} to ${ps[ps.length - 1].file}, `
        + `${ps[0].bottom - ps[0].top} px each${r.measures.fullScale === 1 && r.measures.dpr > 1 ? '; the full shot is at 1x' : ''}`);
    }
  }
  if (earlier) {
    lines.push('', `new since the earlier capture (${comparePath}), matched by text, not by count. `
      + 'An entry here that the change made is a failure the change caused:');
    for (const r of results.filter((x) => !x.error)) {
      const ns = r.measures.newSince;
      if (!ns) { lines.push(`- no earlier capture of ${r.page} ${r.state} at ${r.viewport} to compare`); continue; }
      const parts = COMPARED.filter(([field]) => ns[field].length)
        .map(([field, name, , show]) => `${name}: ${ns[field].slice(0, 6).map(show).join(', ')}${ns[field].length > 6 ? ` and ${ns[field].length - 6} more` : ''}`);
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${parts.join('; ') || 'nothing new'}`
        + `${ns.cut.length ? ` (${ns.cut.join(', ')}: the list holds the first 25, so only those were compared)` : ''}`);
    }
  }
  const untitledRows = results.filter((r) => !r.error && r.measures.untitledCount);
  if (untitledRows.length) {
    lines.push('', 'without a heading: a page-wide section with content and no h1-h6 inside, so a reader '
      + 'scanning by headings (or a screen reader\'s heading list) skips it. A note, not a failure: give it a '
      + 'heading (a visually hidden one is fine) unless it is meant to be unheaded:');
    for (const r of untitledRows) {
      const rows = r.measures.untitled.slice(0, 4).map((u) => `"${u.text || u.tag}"${u.id ? ` (#${u.id})` : ''} ${u.height}px tall`);
      const more = r.measures.untitledCount > 4 ? `; and ${r.measures.untitledCount - 4} more` : '';
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${rows.join('; ')}${more}`);
    }
  }
  const sectionRows = results.filter((r) => !r.error && r.measures.sections && r.measures.sections.length);
  if (sectionRows.length) {
    lines.push('', 'Sections (label: element counts by kind; positions are in measures.json "sections"):');
    for (const r of sectionRows) {
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}:`);
      for (const sec of r.measures.sections) {
        const counts = {};
        sec.elements.forEach((e) => { counts[e.kind] = (counts[e.kind] || 0) + 1; });
        const kinds = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(', ');
        lines.push(`  - ${sec.label}: ${kinds || 'no elements'}`);
      }
    }
  }
  const blanks = results.filter((r) => !r.error && r.measures.blank.flagged);
  if (blanks.length) {
    lines.push('', 'blank: the full-page shot does not show the page below the first screen, so nothing there was '
      + 'checked. Open the PNG. Sections that fade in as you scroll, or load late, may never have appeared. Do not '
      + 'call this page clean; say what was not seen:');
    for (const r of blanks) {
      const names = r.measures.hiddenList.map((h) => `"${h.text || h.tag}"`).slice(0, 3).join(', ');
      lines.push(`- ${r.page} ${r.state} at ${r.viewport}: ${blankText(r.measures.blank)}${r.measures.blank.hidden && names ? ` (${names})` : ''}`);
    }
  }
  if (errors.length) lines.push('', 'Page errors:', ...errors.map((e) => `- ${e}`));
  fs.writeFileSync(path.join(out, `${prefix}summary.md`), lines.join('\n') + '\n');
  console.log(lines.join('\n'));
  console.log(`\nScreenshots + ${prefix}measures.json in ${out}`);
  if (failures.length) {
    console.error(`capture FAILED: ${failures.length} shot(s) are not the page, so this run proves nothing about them:`);
    for (const f of failures) console.error(`- ${f.page} at ${f.viewport}: ${f.error}`);
    process.exit(6);
  }
}

if (require.main === module) {
  main().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
}

module.exports = { joinUrl, readPagesFile, PagesFileError };
