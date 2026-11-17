#!/usr/bin/env node
// Visual QA capture: screenshots + measurements for whole pages at three viewports.
//
//   node <skill folder>/scripts/capture.cjs pages.json [--out DIR]
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
// Writes <out>/<name>-<state>-<width>.png, ...-full.png, measures.json and summary.md.
// Prints only the summary table, so the run stays small in context.

const fs = require('fs');
const path = require('path');

function loadPlaywright() {
  const tries = [
    'playwright',
    path.join(process.cwd(), 'node_modules/playwright'),
    process.env.PLAYWRIGHT_PATH,
  ].filter(Boolean);
  for (const t of tries) { try { return require(t); } catch (_) {} }
  console.error('Playwright not found. Set PLAYWRIGHT_PATH to a node_modules/playwright directory,\n' +
    'or install it once in a scratch dir: npm i playwright && npx playwright install chromium');
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

  // Sideways scroll
  const sideways = document.documentElement.scrollWidth - document.documentElement.clientWidth;

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
      smallTaps.push({ el: label(el), w: Math.round(r.width), h: Math.round(r.height) });
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

function verdicts(m, vpLabel) {
  const phone = vpLabel === '390';
  const out = [];
  out.push(['sideways scroll', m.sideways, m.sideways <= 0]);
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
  const cfgPath = process.argv[2];
  if (!cfgPath) { console.error('usage: capture.cjs pages.json [--out DIR]'); process.exit(1); }
  const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  const outIdx = process.argv.indexOf('--out');
  const out = outIdx > 0 ? process.argv[outIdx + 1] : path.join(path.dirname(cfgPath), 'shots');
  fs.mkdirSync(out, { recursive: true });
  const minText = cfg.minText || 16, minTap = cfg.minTap || 44;
  const setup = cfg.setup ? require(path.resolve(path.dirname(cfgPath), cfg.setup)) : null;

  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const results = [];
  const errors = [];

  for (const vp of VIEWPORTS) {
    const { label, ...ctxOpts } = vp;
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, ...ctxOpts });
    const page = await context.newPage();
    page.on('pageerror', (e) => errors.push(`${label}: ${e.message}`));
    if (setup) await setup(page, cfg.base);

    for (const p of cfg.pages) {
      const state = p.state || 'default';
      const file = `${p.name}-${state}-${label}`;
      try {
        await page.goto(cfg.base + p.path, { waitUntil: 'networkidle' });
        for (const a of p.actions || []) {
          if (a.click) await page.click(a.click);
          if (a.waitFor) await page.waitForSelector(a.waitFor);
          if (a.eval) await page.evaluate(a.eval);
        }
        await page.evaluate(() => document.fonts && document.fonts.ready);
        await page.screenshot({ path: path.join(out, `${file}.png`) });
        await page.screenshot({ path: path.join(out, `${file}-full.png`), fullPage: true });
        const m = await page.evaluate(measure, { items: p.items, minText, minTap });
        results.push({ page: p.name, state, viewport: label, file, measures: m, verdicts: verdicts(m, label) });
      } catch (e) {
        results.push({ page: p.name, state, viewport: label, file, error: e.message.split('\n')[0] });
      }
    }
    await context.close();
  }
  await browser.close();

  fs.writeFileSync(path.join(out, 'measures.json'), JSON.stringify({ results, errors }, null, 2));
  const lines = ['| page | state | vp | fails | notes |', '|---|---|---|---|---|'];
  for (const r of results) {
    if (r.error) { lines.push(`| ${r.page} | ${r.state} | ${r.viewport} | ERROR | ${r.error} |`); continue; }
    const fails = r.verdicts.filter(([, , ok]) => ok === false).map(([k, v]) => `${k}: ${v}`);
    const info = r.verdicts.filter(([, , ok]) => ok === null).map(([k, v]) => `${k}: ${v}`);
    lines.push(`| ${r.page} | ${r.state} | ${r.viewport} | ${fails.join('; ') || 'none'} | ${info.join('; ')} |`);
  }
  if (errors.length) lines.push('', 'Page errors:', ...errors.map((e) => `- ${e}`));
  fs.writeFileSync(path.join(out, 'summary.md'), lines.join('\n') + '\n');
  console.log(lines.join('\n'));
  console.log(`\nScreenshots + measures.json in ${out}`);
})();
