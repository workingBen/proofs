// Refine's change crops (spec §4, "One card per change"): for each change, its before and after
// at 1280 and 390, cut from the built review page's own frames (each laid out at its real width)
// with that one change off, then on, and every other change off. A crop is the union of the
// boxes of the elements the change's `targets` select, measured in the frame with the change off
// and on (so an element it hides or swaps counts), plus CROP_MARGIN, kept inside the page.
// Usage: node crops.cjs <playwright package dir> <page.html> <out dir>
// Writes <out>/<change id>-<before|after>-<1280|390>.png and <out>/crops.json,
// { <change id>: { key, "1280": {x, y, w, h}, "390": {note} } }: CSS pixels in the frame's page, or
// a note for a width where no target is shown (hidden or of no size), which gets no crop. key is
// the card's data-rc-key (review_page.py change_key), so a later build skips crops gone stale. Prints
// one JSON line: { out, crops, notes: [...] }, or { error } when it cannot start. Run through
// review_page.py --crops.
const fs = require("fs");
const path = require("path");
const { launchChromium } = require("./launch.cjs");

// CSS pixels around the targets: enough to show what sits next to them (the row a value is in,
// the space above a heading) without the crop becoming the section.
const CROP_MARGIN = 24;
// The device scale the crops are shot at: sharp on a phone's screen, where the owner reviews.
const CROP_SCALE = 2;
const WIDTHS = [1280, 390];
// The review page is opened wide enough, and its column let out, for both frames to sit at
// scale 1, so a crop is the frame's own pixels rather than a scaled-down copy.
const PAGE_VIEWPORT = { width: 1600, height: 900 };

// Runs in a frame: the union of the boxes of every element `selectors` select that has a size,
// in the frame page's coordinates, and that page's size; box is null when none is shown.
function measureTargets(selectors) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const s of selectors) {
    let els = [];
    try { els = document.querySelectorAll(s); } catch (e) { continue; }
    for (const el of els) {
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.visibility === "collapse") continue;
      x0 = Math.min(x0, r.left + scrollX); y0 = Math.min(y0, r.top + scrollY);
      x1 = Math.max(x1, r.right + scrollX); y1 = Math.max(y1, r.bottom + scrollY);
    }
  }
  const page = { w: document.documentElement.clientWidth, h: document.documentElement.getBoundingClientRect().height };
  return { box: x1 > x0 ? { x0, y0, x1, y1 } : null, page };
}

// The crop for one width from the off and on measures: their union plus the margin, kept inside
// the page (its width, and the shorter of its two heights, so both crops are the same size and
// neither runs past its frame), in whole pixels that still contain it. null when neither shows a target.
function cropBox(off, on, margin = CROP_MARGIN) {
  const boxes = [off.box, on.box].filter(Boolean);
  if (!boxes.length) return null;
  const w = Math.min(off.page.w, on.page.w), h = Math.min(off.page.h, on.page.h);
  const x0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.x0)) - margin));
  const y0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.y0)) - margin));
  const x1 = Math.min(Math.floor(w), Math.ceil(Math.max(...boxes.map((b) => b.x1)) + margin));
  const y1 = Math.min(Math.floor(h), Math.ceil(Math.max(...boxes.map((b) => b.y1)) + margin));
  if (x1 <= x0 || y1 <= y0) return null;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

async function settle(frame) {
  await frame.evaluate(() => document.fonts.ready.then(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))));
}

// Both frames show exactly `ids` (the engine's test-only rpRefine.only), laid out and painted.
async function show(page, frames, ids) {
  await page.evaluate((ids) => window.rpRefine.only(ids), ids);
  for (const w of WIDTHS) {
    await page.waitForFunction(([w, want]) => {
      const f = document.querySelector(`iframe.rp-rc-frame[data-rc-width="${w}"]`);
      return f && f.dataset.rcReady === "1" && !f.style.transform && f.contentDocument &&
        (f.contentDocument.documentElement.getAttribute("data-rc") || "") === want;
    }, [w, ids.join(" ")], { timeout: 15000 });
    await settle(frames[w]);
  }
}

// A PNG of `box` (CSS pixels in the frame's page) of the frame at width w, from the review page.
async function shoot(page, w, box, file) {
  const at = await page.evaluate((w) => {
    const r = document.querySelector(`iframe.rp-rc-frame[data-rc-width="${w}"]`).getBoundingClientRect();
    return { x: r.left + scrollX, y: r.top + scrollY };
  }, w);
  await page.screenshot({ path: file, fullPage: true, clip: { x: at.x + box.x, y: at.y + box.y, width: box.w, height: box.h } });
}

async function main(pw, pagePath, outDir) {
  const { chromium } = require(pw);
  const browser = await launchChromium(chromium, process.env);
  try {
    const ctx = await browser.newContext({ viewport: PAGE_VIEWPORT, deviceScaleFactor: CROP_SCALE });
    const page = await ctx.newPage();
    await page.goto("file://" + path.resolve(pagePath));
    const info = await page.evaluate(() => {
      const prev = document.querySelector("[data-rc-preview]");
      if (!prev) return null;
      const id = prev.dataset.rcPreview;
      const S = JSON.parse(document.getElementById("rp-spec").textContent);
      return { id, changes: S.sections.flatMap((s) => s.items || []).filter((i) => i.refine === id) };
    });
    if (!info) return { error: `${pagePath} has no Refine preview` };
    // Each change card carries its targets (data-rc-targets, a JSON list of selectors).
    const targets = {}, keys = {};
    for (const [id, t, key] of await page.evaluate(() => Array.from(
      document.querySelectorAll("[data-rc-change][data-rc-targets]"),
      (el) => [el.dataset.rcChange, JSON.parse(el.dataset.rcTargets), el.dataset.rcKey]))) {
      targets[id] = t;
      keys[id] = key;
    }
    // Let the column out so both frames fit at scale 1; hide the page's fixed and sticky bars,
    // which a full-page shot would paint over the frames.
    await page.evaluate(() => {
      const st = document.createElement("style");
      st.textContent = ".rp-main { max-width: none !important; }";
      document.head.appendChild(st);
      for (const el of document.querySelectorAll("body *")) {
        const p = getComputedStyle(el).position;
        if (p === "fixed" || p === "sticky") el.style.setProperty("visibility", "hidden", "important");
      }
      window.dispatchEvent(new Event("resize"));
    });
    await page.waitForFunction(() => {
      const f = document.querySelectorAll("iframe.rp-rc-frame");
      return f.length > 0 && Array.from(f).every((x) => x.dataset.rcReady === "1" && !x.style.transform);
    }, null, { timeout: 15000 });
    const frames = {};
    for (const w of WIDTHS) {
      frames[w] = await (await page.$(`iframe.rp-rc-frame[data-rc-width="${w}"]`)).contentFrame();
      // A transition would be caught part way from off to on; shoot the end of it.
      await frames[w].evaluate(() => {
        const st = document.createElement("style");
        st.textContent = "*, *::before, *::after { transition: none !important; animation: none !important; }";
        document.head.appendChild(st);
      });
    }

    fs.mkdirSync(outDir, { recursive: true });
    const crops = {}, notes = [];
    for (const c of info.changes) {
      const sels = targets[c.id] || [];
      const m = { off: {}, on: {} };
      for (const [state, ids] of [["off", []], ["on", [c.id]]]) {
        await show(page, frames, ids);
        for (const w of WIDTHS) m[state][w] = await frames[w].evaluate(measureTargets, sels);
      }
      crops[c.id] = { key: keys[c.id] };
      for (const w of WIDTHS) {
        const box = cropBox(m.off[w], m.on[w]);
        if (box) { crops[c.id][w] = box; continue; }
        const note = `Change ${c.num}: ${sels.join(", ")} ${sels.length > 1 ? "are" : "is"} not shown at ${w} px wide ` +
          `(hidden or of no size, with the change off and on), so there is no crop at this width.`;
        crops[c.id][w] = { note };
        notes.push(note);
      }
      for (const [state, ids] of [["before", []], ["after", [c.id]]]) {
        await show(page, frames, ids);
        for (const w of WIDTHS) {
          const box = crops[c.id][w];
          if (box.note === undefined) await shoot(page, w, box, path.join(outDir, `${c.id}-${state}-${w}.png`));
        }
      }
    }
    await page.evaluate(() => window.rpRefine.only(null));
    fs.writeFileSync(path.join(outDir, "crops.json"), JSON.stringify(crops, null, 2) + "\n");
    return { out: outDir, crops, notes };
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  const [pw, pagePath, outDir] = process.argv.slice(2);
  main(pw, pagePath, path.resolve(outDir))
    .then((r) => console.log(JSON.stringify(r)))
    .catch((e) => { console.log(JSON.stringify({ error: "crops crashed: " + (e && e.message) })); process.exit(1); });
}

module.exports = { CROP_MARGIN, CROP_SCALE, measureTargets, cropBox };
