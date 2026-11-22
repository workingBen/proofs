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
// --sizes picks viewports by label (default: all of 1440, 1280, 390).
// PROOFS_BASE_URL, when set, replaces "base" (so it runs unchanged after with_server.py --).
// --evidence <label> prefixes every file the run writes with "<label>-" (a before and an
// after run can share one --out) and also writes <out>/<label>.json in the shape pr-qa reads.
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
let launchChromium, HOW_TO;
try {
  ({ launchChromium, HOW_TO } = require(LAUNCH));
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

// Runs in the page. Returns raw numbers; pass/fail is decided in Node.
function measure({ items, minText, minTap }) {
  const vw = document.documentElement.clientWidth;
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

  // Words split across lines ("Wildflo-wer")
  const midWord = [];
  const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (tw.nextNode() && midWord.length < 20) {
    const node = tw.currentNode;
    const el = node.parentElement;
    if (!el || !visible(el) || el.closest('svg,code,pre,textarea')) continue;
    const re = /\S{4,}/g; let m;
    while ((m = re.exec(node.textContent))) {
      const range = document.createRange();
      range.setStart(node, m.index); range.setEnd(node, m.index + m[0].length);
      const tops = new Set([...range.getClientRects()].map((r) => Math.round(r.top)));
      if (tops.size > 1) midWord.push(m[0].slice(0, 30));
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
    midWord,
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

// Folds the three overflow signals into m.sideways (the worst of them) and m.signals.
function overflowOf(m) {
  const cw = m.clientWidth;
  const scroll = m.scrollWidth - cw;
  const clipped = m.widestRight - cw;
  const image = Math.round(m.pngWidth / m.dpr) - cw;
  const signals = [];
  if (scroll > 1) signals.push('scroll');
  else if (clipped > 1) signals.push('clipped');
  if (image > 1) signals.push('image');
  m.signals = signals;
  m.sideways = Math.max(scroll, clipped, image, 0);
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
  if (m.items) {
    out.push(['chrome before first item', m.items.chromeShare, m.items.chromeShare < 0.4]);
    out.push(['items in first screen', m.items.fullyVisible, null]);
    out.push(['median item height', m.items.medianHeight, null]);
  }
  return out;
}

(async () => {
  const argv = process.argv.slice(2);
  const opt = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
  const cfgPath = argv[0];
  if (!cfgPath || cfgPath.startsWith('--')) {
    console.error('usage: capture.cjs pages.json [--out DIR] [--sizes 390,1440] [--evidence before|after]');
    process.exit(1);
  }
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const out = opt('--out') || path.join(path.dirname(cfgPath), 'shots');
  const evidence = opt('--evidence');
  const prefix = evidence ? `${evidence}-` : '';
  const sizes = opt('--sizes') ? opt('--sizes').split(',').map((x) => x.trim()) : null;
  const viewports = sizes ? VIEWPORTS.filter((v) => sizes.includes(v.label)) : VIEWPORTS;
  if (!viewports.length) {
    console.error(`--sizes ${sizes.join(',')} matches none of ${VIEWPORTS.map((v) => v.label).join(', ')}`);
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
      try {
        await page.goto(base + p.path, { waitUntil: 'networkidle' });
        for (const a of p.actions || []) {
          if (a.click) await page.click(a.click);
          if (a.waitFor) await page.waitForSelector(a.waitFor);
          if (a.eval) await page.evaluate(a.eval);
        }
        await page.evaluate(() => document.fonts && document.fonts.ready);
        await page.screenshot({ path: path.join(out, `${file}.png`) });
        await page.screenshot({ path: path.join(out, `${file}-full.png`), fullPage: true });
        const m = await page.evaluate(measure, { items: p.items, minText, minTap });
        if (m.innerWidth !== vp.width) {
          untrusted = `the browser laid the page out at ${m.innerWidth} px, not ${vp.width} px; the capture is not trustworthy`;
          break;
        }
        m.pngWidth = pngWidth(path.join(out, `${file}-full.png`));
        overflowOf(m);
        results.push({ page: p.name, state, viewport: label, file, measures: m, verdicts: verdicts(m, label) });
      } catch (e) {
        results.push({ page: p.name, state, viewport: label, file, error: e.message.split('\n')[0] });
      }
    }
    await context.close();
  }
  await browser.close();
  if (untrusted) { console.error(untrusted); process.exit(3); }

  fs.writeFileSync(path.join(out, `${prefix}measures.json`), JSON.stringify({ results, errors }, null, 2));
  if (evidence) {
    const shots = results.filter((r) => !r.error).map((r) => ({
      label: r.viewport, size: r.viewport === '390' ? 'phone' : 'desktop',
      slug: `${r.page}-${r.state}${r.viewport === '1280' ? '-1280' : ''}`, pageLabel: r.page,
      path: cfg.pages.find((p) => p.name === r.page && (p.state || 'default') === r.state).path,
      file: `${r.file}-full.png`,
      overflow: r.measures.sideways, overflowing: r.measures.overflowing,
      smallTargets: r.measures.smallTaps.map((t) => ({ text: t.el, tag: t.tag, width: t.w, height: t.h })), scrollWidth: r.measures.scrollWidth, clientWidth: r.measures.clientWidth,
      widestRight: r.measures.widestRight, pngWidth: r.measures.pngWidth, innerWidth: r.measures.innerWidth,
      errors: errors.filter((e) => e.startsWith(`${r.viewport}:`)),
    }));
    fs.writeFileSync(path.join(out, `${evidence}.json`), JSON.stringify({ shots }, null, 2));
  }
  const lines = ['| page | state | vp | fails | notes |', '|---|---|---|---|---|'];
  const seen = new Set();
  for (const r of results) {
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
  };
  if (seen.size) lines.push('', ...[...seen].map((s) => `- ${WORDS[s]}`));
  if (errors.length) lines.push('', 'Page errors:', ...errors.map((e) => `- ${e}`));
  fs.writeFileSync(path.join(out, `${prefix}summary.md`), lines.join('\n') + '\n');
  console.log(lines.join('\n'));
  console.log(`\nScreenshots + ${prefix}measures.json in ${out}`);
})();
