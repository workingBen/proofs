#!/usr/bin/env node
// Visual QA capture: screenshots + measurements for whole pages at three viewports.
//
//   node <skill folder>/scripts/capture.cjs pages.json [--out DIR] [--sizes 390,1440] [--evidence before|after]
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
//
// --sizes picks viewports by label (default: all of 1440, 1280, 390), or adds a desktop width
// such as 1040 (400 to 2560), for a shot just above a breakpoint.
// PROOFS_BASE_URL, when set, replaces "base" (so it runs unchanged after with_server.py --).
// --evidence <label> prefixes every file the run writes with "<label>-" (a before and an
// after run can share one --out) and also writes <out>/<label>.json in the shape pr-qa reads.
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
  if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) {
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

// Runs in the page. Returns raw numbers; pass/fail is decided in Node.
// `edge`, when given, is the screen's width to measure overflow against (the plain
// recheck of a phone layout that came out wider than the screen).
function measure({ items, minText, minTap, edge, offCenterPx = 16 }) {
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
    if (px < minText - 0.5) smallText.push({ text: node.textContent.trim().slice(0, 40), px: +px.toFixed(1) });
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
      smallTaps.push({ el: label(el), tag: el.tagName.toLowerCase(), w: Math.round(r.width), h: Math.round(r.height) });
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
      offCenter.push({ text: label(el), tag: el.tagName.toLowerCase(), left: Math.round(left), right: Math.round(right) });
    }
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
    items: itemStats,
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

// Folds the overflow signals into m.sideways (the worst of them) and m.signals. A phone
// layout that came out wider than the screen (m.zoomedOut) is measured against the screen.
function overflowOf(m) {
  const z = m.zoomedOut;
  const cw = z ? z.screenWidth : m.clientWidth;
  const scroll = (z ? z.layoutWidth : m.scrollWidth) - cw;
  const clipped = m.widestRight - cw;
  const image = Math.round(m.pngWidth / m.dpr) - cw;
  const signals = [];
  if (z) signals.push('zoomed');
  else if (scroll > 1) signals.push('scroll');
  else if (clipped > 1) signals.push('clipped');
  if (image > 1 && !z) signals.push('image');
  m.signals = signals;
  m.sideways = Math.max(scroll, clipped, image, 0);
}

// Goes to the page and runs its actions (shared by the capture and the plain recheck).
async function openPage(page, base, p) {
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
}

// An emulated phone lays the page out wider than its screen when the content is too wide,
// as a real phone zooms out to fit (Rails run 1: 407 px at 390). A browser that ignores the
// viewport (headless Chrome on macOS once had a minimum width) is wide in a plain desktop
// context too. So load the page once more at the same width without phone emulation: if
// that context is the asked width and the content runs past it, the overflow is the page's.
async function recheckWide(browser, vp, base, p, setup, minText, minTap) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  try {
    const page = await context.newPage();
    if (setup) await setup(page, base);
    await openPage(page, base, p);
    const flat = await page.evaluate(measure, { items: p.items, minText, minTap, edge: vp.width });
    const real = flat && flat.innerWidth === vp.width
      && Math.max(flat.scrollWidth || 0, flat.widestRight || 0) > vp.width + 1;
    return real ? flat : null;
  } finally {
    await context.close();
  }
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
    console.error('usage: capture.cjs pages.json [--out DIR] [--sizes 390,1440] [--evidence before|after]');
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
        await openPage(page, base, p);
        await page.screenshot({ path: path.join(out, `${file}.png`) });
        await page.screenshot({ path: path.join(out, `${file}-full.png`), fullPage: true });
        const m = await page.evaluate(measure, { items: p.items, minText, minTap });
        if (m.innerWidth !== vp.width) {
          const flat = vp.isMobile && m.innerWidth > vp.width
            ? await recheckWide(browser, vp, base, p, setup, minText, minTap) : null;
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
        m.midWord = (await page.evaluate(midWordBreaks, { selector: 'body', limit: 20 })).map((w) => w.at);
        m.pngWidth = pngWidth(path.join(out, `${file}-full.png`));
        overflowOf(m);
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
