// Click through a built review page in headless Chromium (or the installed Google Chrome) and report what broke.
// Usage: node smoke.cjs <playwright package dir> <page.html>
// Prints one JSON line: { mode, items, export, problems: [...] }. Exercises the
// first item of each kind the page's frame uses, and on question and session
// pages checks that open questions sit directly under the sticky bar; on review pages it
// also flags a word a mockup breaks mid-word, by item and variant; on the settings page it
// types a refused value and a good one, and measures every tap target in every group. On a
// Refine page it checks the base against the before shots, finds changes that overlap, and runs
// the design checks inside each frame with each change on alone and all on (refineChecks). Run
// through review_page.py --smoke rather than directly; an optional third argument is the folder
// of a Refine page's before shots, when they are not beside its base snapshot.
const path = require("path");
const { chromium } = require(process.argv[2]);
const { launchChromium } = require("./launch.cjs");
const { midWordBreaks } = require("./midword.cjs");
const { designChecks } = require("./designchecks.cjs");
const { layoutSignature, signatureFromSection, similarity, NEAR_COPY } = require("./signature.cjs");
const { compareShots, renderBase, shotNames, FIDELITY } = require("./fidelity.cjs");
const fs = require("fs");
const file = "file://" + path.resolve(process.argv[3]);
const shotsDir = process.argv[4] || null;

// One box's design check results as lines, worded the same for a mockup and a Refine frame:
// problems, and notes that are never problems (peeks, unmeasured contrast, off-scale sizes).
function designLines(where, d, w) {
  const problems = [], notes = [];
  if (d.contrast.length) problems.push(`${where}: ${d.contrast.length} text elements below AA contrast at ${w}px`);
  if (d.smallTargets.length) problems.push(`${where}: ${d.smallTargets.length} tap targets under 44x44 at ${w}px`);
  if (d.longLines.length) problems.push(`${where}: ${d.longLines.length} lines over 80 characters at ${w}px`);
  if (d.edges.length) problems.push(`${where}: ${d.edges.length} left edges 1 to 6px out of line at ${w}px`);
  // A row with a partly visible item is "cut"; one whose items sit wholly past the edge "hides" them.
  const cutRows = d.clippedRows.filter((c) => c.cut !== null);
  const hideRows = d.clippedRows.filter((c) => c.cut === null);
  if (cutRows.length) problems.push(`${where}: ${cutRows.length} row${cutRows.length > 1 ? "s" : ""} cut at the right edge at ${w}px (${cutRows.map((c) => `"${c.cut}" cut${c.hidden.length ? `; ${c.hidden.length} more hidden past it` : ""}`).join("; ")})`);
  for (const c of hideRows) problems.push(`${where}: 1 row hides ${c.hidden.length} item${c.hidden.length > 1 ? "s" : ""} past the right edge at ${w}px (${c.hidden.map((h) => `"${h}"`).join(", ")})`);
  if (d.peekRows.length) notes.push(`${where}: ${d.peekRows.length} carousel${d.peekRows.length > 1 ? "s" : ""} show a partly visible card at ${w}px (${d.peekRows.map((c) => `"${c.cut || c.text}"`).join("; ")}); a swipe peek, check it is meant`);
  if (d.unmeasured.length) {
    const why = [...new Set(d.unmeasured.map((u) => u.reason.replace(/^contrast: not measured \((.*)\)$/, "$1")))];
    notes.push(`${where}: contrast not measured for ${d.unmeasured.length} text elements (${why.join("; ")}) at ${w}px`);
  }
  if (d.offScale.length) notes.push(`${where}: ${d.offScale.length} text sizes off the page's own scale at ${w}px (${d.offScale.map((o) => o.size + "px").join(", ")})`);
  return { problems, notes };
}

// What identifies one entry of each design check list, so a Refine state is held only to what
// it adds to the page as it is: a text still under AA with a change on is the page's, not the change's.
const CHECK_KEYS = {
  contrast: (e) => e.text, unmeasured: (e) => e.text + "|" + e.reason, smallTargets: (e) => e.text,
  longLines: (e) => e.text, edges: (e) => e.a + "|" + e.b, offScale: (e) => e.text,
  clippedRows: (e) => e.text + "|" + e.cut, peekRows: (e) => e.text,
};
function minus(list, base, key) {
  const left = new Map();
  for (const e of base) left.set(key(e), (left.get(key(e)) || 0) + 1);
  return list.filter((e) => {
    const n = left.get(key(e)) || 0;
    if (n) { left.set(key(e), n - 1); return false; }
    return true;
  });
}
function added(d, base) {
  const out = {};
  for (const k of Object.keys(CHECK_KEYS)) out[k] = minus(d[k] || [], base[k] || [], CHECK_KEYS[k]);
  return out;
}

// What `added` leaves out: an entry the page already had that a change makes worse (lower
// contrast, a smaller tap target, a longer line). Never a problem, since the page had it, but a
// note, so a change does not pass for deepening a failure.
const WORSE = {
  contrast: { val: (e) => e.ratio, worse: (now, was) => now < was - 0.05,
    what: ["text element already below AA contrast", "text elements already below AA contrast"],
    say: (e, b) => `"${e.text}" ${b.ratio.toFixed(2)} to ${e.ratio.toFixed(2)}` },
  smallTargets: { val: (e) => Math.min(e.w, e.h), worse: (now, was) => now < was - 0.5,
    what: ["tap target already under 44x44", "tap targets already under 44x44"],
    say: (e, b) => `"${e.text}" ${b.w}x${b.h} to ${e.w}x${e.h}` },
  longLines: { val: (e) => e.chars, worse: (now, was) => now > was,
    what: ["line already over 80 characters", "lines already over 80 characters"],
    say: (e, b) => `"${e.text}" ${b.chars} to ${e.chars} characters` },
};
function worseLines(where, d, base, w) {
  const out = [];
  for (const [k, c] of Object.entries(WORSE)) {
    const left = new Map();
    for (const b of base[k] || []) {
      const key = CHECK_KEYS[k](b);
      if (!left.has(key)) left.set(key, []);
      left.get(key).push(b);
    }
    const hits = [];
    for (const e of d[k] || []) {
      const was = (left.get(CHECK_KEYS[k](e)) || []).shift();
      if (was && c.worse(c.val(e), c.val(was))) hits.push(c.say(e, was));
    }
    if (hits.length) out.push(`${where}: makes ${hits.length} ${c.what[hits.length > 1 ? 1 : 0]} worse at ${w}px (${hits.join("; ")})`);
  }
  return out;
}

// Runs in a Refine frame. The first call (no `ids`) records, for every element, the computed
// value of each property any change declares; a later call returns [index, property] for each
// element whose value of any of those properties is not what it was, and [index, "markup"] for
// each element a swap took out. Every change is diffed on the union of all changes' declared
// longhands (custom properties too), not only its own: a change that sets --accent changes the
// color of whatever reads var(--accent), the property another change may set outright. Declared
// longhands come from the frame's <style data-rc-css>. The first call also records, per element,
// the properties each change's rules declare on it directly (window.__rcDirect), measured with
// every change's attribute on and on the base DOM, so it holds for an element a swap later takes
// out. An overlap needs one of the two changes to declare the property on the element itself:
// getComputedStyle gives used values for width, height and margins, so a reflow from one change
// would otherwise meet a layout property another declares on some other element.
function styleDiff({ ids }) {
  const declared = {}, parts = [];
  const sheet = Array.from(document.styleSheets).find((sh) => sh.ownerNode && sh.ownerNode.hasAttribute("data-rc-css"));
  const walk = (rules) => {
    for (const r of rules) {
      if (r.cssRules && !r.selectorText) { walk(r.cssRules); continue; }
      if (!r.selectorText || !r.style) continue;
      const longhands = Array.from({ length: r.style.length }, (_, i) => r.style[i]);
      for (const m of r.selectorText.matchAll(/\[data-rc~="([a-z0-9-]+)"\]/g)) {
        const set = declared[m[1]] || (declared[m[1]] = new Set());
        longhands.forEach((l) => set.add(l));
      }
      for (const part of r.selectorText.split(/,\s*(?=html\[data-rc~=)/)) {
        const m = part.match(/^html\[data-rc~="([a-z0-9-]+)"\]/);
        if (m) parts.push([part, m[1], longhands]);
      }
    }
  };
  if (sheet) walk(sheet.cssRules);
  if (!ids) {
    const props = [...new Set(Object.values(declared).flatMap((s) => [...s]))];
    window.__rcEls = [document.body, ...document.body.querySelectorAll("*")];
    window.__rcProps = props;
    window.__rcBase = window.__rcEls.map((el) => { const cs = getComputedStyle(el); return props.map((p) => cs.getPropertyValue(p)); });
    const index = new Map(window.__rcEls.map((el, i) => [el, i]));
    window.__rcDirect = window.__rcEls.map(() => ({}));
    const root = document.documentElement, was = root.getAttribute("data-rc");
    root.setAttribute("data-rc", Object.keys(declared).join(" "));
    for (const [part, id, longhands] of parts) {
      let els = [];
      try { els = document.querySelectorAll(part); } catch (e) { continue; }
      for (const el of els) {
        const i = index.get(el);
        if (i === undefined) continue;
        const d = window.__rcDirect[i];
        d[id] = [...new Set([...(d[id] || []), ...longhands])];
      }
    }
    if (was === null) root.removeAttribute("data-rc"); else root.setAttribute("data-rc", was);
    return [];
  }
  const out = [];
  window.__rcEls.forEach((el, i) => {
    if (!el.isConnected) { out.push([i, "markup"]); return; }
    const cs = getComputedStyle(el);
    window.__rcProps.forEach((p, j) => { if (cs.getPropertyValue(p) !== window.__rcBase[i][j]) out.push([i, p]); });
  });
  return out;
}

// Runs in a Refine frame: a short name for each element index, the selector of the first rule
// of changes `ids` that matches it (its html[data-rc~] prefix taken off), else #id, .class or tag.
function elementNames({ indices, ids }) {
  const sheet = Array.from(document.styleSheets).find((sh) => sh.ownerNode && sh.ownerNode.hasAttribute("data-rc-css"));
  const sels = [];
  const walk = (rules) => {
    for (const r of rules) {
      if (r.cssRules && !r.selectorText) { walk(r.cssRules); continue; }
      if (!r.selectorText) continue;
      for (const part of r.selectorText.split(/,\s*(?=html\[data-rc~=)/)) {
        const m = part.match(/^html\[data-rc~="([a-z0-9-]+)"\]\s*(.*)$/);
        if (m && ids.includes(m[1])) sels.push(m[2].trim() || "html");
      }
    }
  };
  if (sheet) walk(sheet.cssRules);
  return indices.map((i) => {
    const el = window.__rcEls[i];
    for (const s of sels) { try { if (el.matches(s)) return s; } catch (e) { /* not a selector on its own */ } }
    if (el.id) return "#" + el.id;
    const cls = typeof el.className === "string" && el.className.trim() ? el.className.trim().split(/\s+/)[0] : "";
    return cls ? "." + cls : el.tagName.toLowerCase();
  });
}

// Runs in a Refine frame, after styleDiff's first call recorded the base's elements
// (window.__rcEls): which of them a reader can see, and what each one's own words look like.
// Seen: still in the page, not hidden by display, visibility or opacity (checkVisibility), of a
// size, and not cut away by an ancestor that clips its overflow (height: 0; overflow: hidden).
// Words: an element's own text with how it is set (text-transform, the alpha of its color, the
// content of its ::before and ::after), so color: transparent, text-transform and content:
// read as changed words while the element stays in place. Returns { seen: [index...], words:
// { index: signature } }.
function seenState() {
  const els = window.__rcEls || [];
  const clip = new Map();
  const box = (a) => {
    if (!clip.has(a)) {
      const cs = getComputedStyle(a);
      clip.set(a, cs.overflowX === "visible" && cs.overflowY === "visible" ? null : a.getBoundingClientRect());
    }
    return clip.get(a);
  };
  const shown = (el) => {
    if (!el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, opacityProperty: true, visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return false;
    for (let a = el.parentElement; a && a !== document.documentElement; a = a.parentElement) {
      const b = box(a);
      if (b && (r.right <= b.left || r.left >= b.right || r.bottom <= b.top || r.top >= b.bottom)) return false;
    }
    return true;
  };
  const alpha = (c) => { const m = /rgba?\(([^)]*)\)/.exec(c || ""); const p = m ? m[1].split(/[\s,/]+/).filter(Boolean) : []; return p.length > 3 ? parseFloat(p[3]) : 1; };
  const out = { seen: [], words: {} };
  els.forEach((el, i) => {
    if (!shown(el)) return;
    out.seen.push(i);
    const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.data).join("").replace(/\s+/g, " ").trim();
    const cs = getComputedStyle(el);
    const pseudo = ["::before", "::after"].map((p) => getComputedStyle(el, p).content).filter((c) => c && c !== "none" && c !== "normal");
    if (!own && !pseudo.length) return;
    const ink = cs.webkitTextFillColor && alpha(cs.webkitTextFillColor) === 0 ? 0 : alpha(cs.color);
    out.words[i] = JSON.stringify([own, own ? cs.textTransform : "", own ? (ink > 0 && parseFloat(cs.fontSize) > 0) : true, pseudo]);
  });
  return out;
}

// Runs in a Refine frame: for each change, how many elements each of its targets and each of its
// swaps' selectors match now, or "throws" for one that is not a valid selector.
function selectorCounts(changes) {
  const count = (sel) => { try { return document.querySelectorAll(sel).length; } catch (e) { return "throws"; } };
  return changes.map((c) => ({
    targets: (c.targets || []).map((t) => [t, count(t)]),
    swaps: Array.from(document.querySelectorAll("template[data-rc-swap]"))
      .filter((t) => t.dataset.rcSwap === c.id).map((t) => [t.dataset.rcTarget, count(t.dataset.rcTarget)]),
  }));
}

// A PNG's size from its header, without decoding it.
function pngSize(file) {
  const b = fs.readFileSync(file);
  return b.length > 24 ? { width: b.readUInt32BE(16), height: b.readUInt32BE(20) } : null;
}
// CSS pixels a frame may differ from its before shot in height: rounding (a frame is a whole
// number of pixels, a phone shot two device pixels to one).
const HEIGHT_SLACK = 2;

// What one change on hides or rewords, against the page as it is, at one width: problem lines
// when the change has no removes line, notes when it has (the reader sees its removes lines on
// the card; this says what they cover). Hidden elements are counted where they start, not once
// per descendant.
async function lostLines(f, st, was, now, w, label, problems, notes) {
  if (!was || !now) return;
  const shown = new Set(now.seen);
  const lost = was.seen.filter((i) => !shown.has(i));
  const reworded = [...new Set([...Object.keys(was.words), ...Object.keys(now.words)])]
    .map(Number).filter((i) => shown.has(i) && was.words[i] !== now.words[i]);
  const top = lost.length ? await f.evaluate((ix) => {
    const set = new Set(ix.map((i) => window.__rcEls[i]));
    return ix.filter((i) => { for (let a = window.__rcEls[i].parentElement; a; a = a.parentElement) if (set.has(a)) return false; return true; });
  }, lost) : [];
  const c = st.change, has = (c.removes || []).length > 0;
  const say = async (ix, what) => {
    const names = await f.evaluate(elementNames, { indices: ix.slice(0, 3), ids: [c.id] });
    const list = `${names.join(", ")}${ix.length > 3 ? `, and ${ix.length - 3} more` : ""}`;
    if (has) notes.push(`${label}: change ${c.num} ${what(ix.length)} at ${w}px (${list}); check its removes lines (${c.removes.join("; ")}) cover them`);
    else problems.push(`${label}: change ${c.num} ${what(ix.length)} at ${w}px (${list}) with no removes line saying what and why`);
  };
  if (top.length) await say(top, (n) => `hides ${n} element${n > 1 ? "s" : ""}`);
  if (reworded.length) await say(reworded, (n) => `changes words in ${n} element${n > 1 ? "s" : ""}`);
}

// design-review's Refine mode (spec §2 and §3). The base with every change off, shot as its own
// page at the capture's 1280 and 390, against the before shots (fidelity.cjs); then, inside each
// frame at its own width, the page as it is, each change on alone and all on: computed styles
// for overlaps, and the design checks, mid-word breaks and sideways scroll. A state's problem
// lines are what it adds to the page as it is; the page's own findings are notes.
async function refineChecks(browser, page, S, problems, notes) {
  const preview = await page.$("[data-rc-preview]");
  if (!preview) return null;
  const id = await preview.getAttribute("data-rc-preview");
  const baseRel = (await preview.getAttribute("data-rc-base")) || "";
  const label = `item ${id} (Refine)`;
  const changes = S.sections.flatMap((s) => s.items || []).filter((i) => i.refine === id);
  const doc = await page.evaluate((id) => JSON.parse(document.getElementById("rp-rc-base-" + id).textContent), id);
  const out = { item: id, fidelity: {}, overlaps: [], checks: [] };

  const dirs = shotsDir ? [shotsDir]
    : [...new Set([process.cwd(), path.dirname(path.resolve(process.argv[3]))].map((d) => path.dirname(path.resolve(d, baseRel))))];
  for (const w of [1280, 390]) {
    const tried = dirs.flatMap((d) => shotNames(baseRel, w).map((n) => path.join(d, n)));
    const before = tried.find((f) => fs.existsSync(f));
    if (!before) {
      out.fidelity[w] = null;
      problems.push(`${label}: no before shot at ${w} (looked for ${tried.map((f) => path.relative(process.cwd(), f)).join(", ")}); fidelity not measured${shotsDir ? "" : "; pass --shots DIR with the folder of the before shots"}`);
      continue;
    }
    const r = await compareShots(await renderBase(browser, doc, w, []), before);
    out.fidelity[w] = { pixelRatio: r.pixelRatio, signature: r.signature, before };
    if (r.pixelRatio > FIDELITY.pixelRatio) problems.push(`${label}: base differs from the page at ${w} (pixel ratio ${r.pixelRatio.toFixed(3)})`);
  }

  await page.waitForFunction(() => {
    const f = document.querySelectorAll("iframe.rp-rc-frame");
    return f.length > 0 && Array.from(f).every((x) => x.dataset.rcReady === "1");
  }, null, { timeout: 15000 });
  const frames = {};
  for (const w of [1280, 390]) {
    frames[w] = await (await page.$(`iframe.rp-rc-frame[data-rc-width="${w}"]`)).contentFrame();
    // A transition would show a value part way from off to on; measure the end of it.
    await frames[w].evaluate(() => {
      const st = document.createElement("style");
      st.textContent = "*, *::before, *::after { transition: none !important; }";
      document.head.appendChild(st);
    });
  }
  const states = [{ key: "base", ids: [], where: `${label}, the page as it is` },
    ...changes.map((c) => ({ key: c.num, ids: [c.id], where: `${label}, change ${c.num} on`, change: c })),
    ...(changes.length > 1 ? [{ key: "all", ids: changes.map((c) => c.id), where: `${label}, all changes on` }] : [])];
  // Each change's targets, from its card (the spec items carry no selectors).
  const cardTargets = Object.fromEntries(await page.evaluate(() => Array.from(
    document.querySelectorAll("[data-rc-change][data-rc-targets]"), (el) => [el.dataset.rcChange, JSON.parse(el.dataset.rcTargets)])));
  const probe = changes.map((c) => ({ id: c.id, targets: cardTargets[c.id] || [] }));
  const base = {}, touched = {}, shownIn = {}, counts = {};
  for (const st of states) {
    await page.evaluate((ids) => window.rpRefine.only(ids), st.ids);
    for (const w of [1280, 390]) {
      const f = frames[w];
      const rc = await f.evaluate(() => document.documentElement.getAttribute("data-rc") || "");
      if (rc !== st.ids.join(" ")) problems.push(`${label}: the ${w} frame shows "${rc}" for ${st.where.slice(label.length + 2)}`);
      const d = await designChecks(f, "body", { width: w });
      const mid = await f.evaluate(midWordBreaks, { selector: "body", limit: 40 });
      const over = await f.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const diff = await f.evaluate(styleDiff, { ids: st.key === "base" ? null : st.ids });
      if (st.change) touched[w + "|" + st.change.num] = diff;
      if (st.key !== "all") {
        shownIn[w + "|" + st.key] = await f.evaluate(seenState);
        counts[w + "|" + st.key] = await f.evaluate(selectorCounts, probe);
      }
      out.checks.push({ state: st.key, width: w, contrast: d.contrast.length, smallTargets: d.smallTargets.length,
        longLines: d.longLines.length, edges: d.edges.length, clippedRows: d.clippedRows.length,
        midWord: mid.length, sideways: Math.max(0, over) });
      if (st.key === "base") {
        base[w] = { d, mid, over };
        const l = designLines(st.where, d, w);
        notes.push(...l.problems, ...l.notes);
        for (const b of mid) notes.push(`${st.where}: "${b.at}" breaks mid-word at ${w}px wide`);
        if (over > 0) notes.push(`${st.where}: the page scrolls sideways by ${over}px at ${w}px wide`);
        continue;
      }
      const l = designLines(st.where, added(d, base[w].d), w);
      problems.push(...l.problems);
      notes.push(...l.notes, ...worseLines(st.where, d, base[w].d, w));
      if (st.change) await lostLines(f, st, shownIn[w + "|base"], shownIn[w + "|" + st.key], w, label, problems, notes);
      for (const b of minus(mid, base[w].mid, (e) => e.at)) problems.push(`${st.where}: "${b.at}" breaks mid-word at ${w}px wide`);
      if (over > Math.max(0, base[w].over)) problems.push(`${st.where}: the page scrolls sideways by ${over}px at ${w}px wide`);
    }
  }
  // A target or swap selector that is not a selector, or that matches nothing with the change
  // off or on at either width, means the change's crops, overlap and removes checks see nothing.
  changes.forEach((c, k) => {
    for (const kind of ["targets", "swaps"]) {
      const sels = (counts["1280|base"] || [])[k] ? counts["1280|base"][k][kind].map(([sel]) => sel) : [];
      sels.forEach((sel, j) => {
        const all = [1280, 390].flatMap((w) => ["base", c.num].map((key) => ((counts[w + "|" + key] || [])[k] || { [kind]: [] })[kind][j]));
        const what = kind === "targets" ? "target" : "swap";
        if (all.some((x) => x && x[1] === "throws")) problems.push(`${label}: change ${c.num}: ${what} ${sel} is not a valid selector`);
        else if (all.every((x) => x && x[1] === 0)) problems.push(`${label}: change ${c.num}: ${what} ${sel} matches nothing`);
      });
    }
  });

  // The frames' heights against the before shots': the preview must lay the page out as tall as
  // it is, or 100%-of-the-viewport layouts are wrong in it (an app shell 150 px tall, a 100vh
  // hero growing without bound).
  await page.evaluate(() => window.rpRefine.only([]));
  await page.waitForFunction(() => Array.from(document.querySelectorAll("iframe.rp-rc-frame"))
    .every((x) => (x.contentDocument.documentElement.getAttribute("data-rc") || "") === ""), null, { timeout: 15000 });
  await page.waitForTimeout(300);
  out.heights = {};
  for (const w of [1280, 390]) {
    const frame = await page.evaluate((w) => parseFloat(document.querySelector(`iframe.rp-rc-frame[data-rc-width="${w}"]`).style.height), w);
    const fid = out.fidelity[w];
    const png = fid ? pngSize(fid.before) : null;
    const before = png ? Math.round(png.height * w / png.width) : null;
    out.heights[w] = { frame, before };
    if (before !== null && Math.abs(frame - before) > HEIGHT_SLACK) {
      problems.push(`${label}: the ${w} frame lays the page out ${Math.round(frame)} px tall, but the before shot is ${before} px; the preview does not show the page as it is`);
    }
  }
  await page.evaluate(() => window.rpRefine.only(null));

  // Overlaps: two changes that change the same property on the same element, at either width,
  // or one swaps an element (markup) the other changes in any way.
  const seen = new Set();
  for (let i = 0; i < changes.length; i++) {
    for (let j = i + 1; j < changes.length; j++) {
      const a = changes[i], b = changes[j];
      for (const w of [1280, 390]) {
        const ta = touched[w + "|" + a.num] || [], tb = touched[w + "|" + b.num] || [];
        const props = (t) => { const m = new Map(); for (const [e, p] of t) m.set(e, (m.get(e) || new Set()).add(p)); return m; };
        const pa = props(ta), pb = props(tb);
        const shared = [...pa.keys()].filter((e) => pb.has(e));
        const direct = shared.length ? await frames[w].evaluate((ix) => ix.map((i) => window.__rcDirect[i]), shared) : [];
        const on = (k, c) => direct[k][c.id] || [];
        const both = [];  // [element index, property, which side swaps it or null]
        shared.forEach((e, k) => {
          const sa = pa.get(e), sb = pb.get(e);
          if (sa.has("markup") || sb.has("markup")) {
            const swapper = sa.has("markup") ? a : b, other = swapper === a ? b : a;
            const otherSet = swapper === a ? sb : sa;
            // "markup" on both sides: both swap it. Otherwise the other change must have a rule on
            // this element itself, not one it inherits from or is pushed around by.
            if (otherSet.has("markup")) { both.push([e, "markup", swapper]); return; }
            for (const p of otherSet) if (on(k, other).length) both.push([e, p, swapper]);
          } else {
            for (const p of sa) if (sb.has(p) && (on(k, a).includes(p) || on(k, b).includes(p))) both.push([e, p, null]);
          }
        });
        if (!both.length) continue;
        const names = await frames[w].evaluate(elementNames, { indices: both.map(([e]) => e), ids: [a.id, b.id] });
        both.forEach(([, prop, swapper], k) => {
          const key = [a.num, b.num, names[k], prop].join("|");
          if (seen.has(key)) return;
          seen.add(key);
          out.overlaps.push({ a: a.num, b: b.num, element: names[k], property: prop });
          if (!swapper) problems.push(`${label}: changes ${a.num} and ${b.num} both change ${prop} on ${names[k]}`);
          else {
            const other = swapper === a ? b : a;
            problems.push(prop === "markup"
              ? `${label}: changes ${a.num} and ${b.num} both swap ${names[k]}`
              : `${label}: change ${swapper.num} swaps ${names[k]}, which change ${other.num} also changes (${prop})`);
          }
        });
      }
    }
  }
  return out;
}

// The claude.ai runtime, stubbed: a db that stores in memory (window.__dbMode "hold" keeps
// each write out until window.__release()), and a comments capability whose
// canSendToClaude answers window.__can and whose sendToClaude records what it got and
// rejects with window.__sendErr when that is set. The page cannot reach claude.ai here.
function installRuntime(cfg) {
  window.__sent = [];
  window.__held = [];
  window.__dbMode = "ok";
  window.__can = cfg.can;
  window.__sendErr = null;
  window.__release = () => { const h = window.__held; window.__held = []; h.forEach((f) => f()); };
  const db = { collection: () => ({
    get: async () => ({ docs: [] }),
    doc: () => ({ set: () => window.__dbMode === "hold" ? new Promise((r) => window.__held.push(r)) : Promise.resolve() }),
  }) };
  const comments = {
    canSendToClaude: async () => window.__can,
    anchorFor: async () => ({ path: "stub", x: 0, y: 0 }),
    sendToClaude: async (t) => {
      window.__sent.push({ text: t.text, anchor: !!t.anchor, sync: document.body.getAttribute("data-rp-sync") });
      if (window.__sendErr) throw { code: window.__sendErr, message: "stub" };
      return { threadId: "t1", commentId: "c1" };
    },
  };
  window.claude = { use: (n) => new Promise((r) => setTimeout(() => r(n === "db" ? db : n === "comments" ? comments : null), 20)) };
}

// Drive Send to Claude: hidden with no runtime, disabled with the reason when no session
// listens, enabled once one does, waits for Saved, a short text, the error lines, and the
// pickup line on the next load.
async function sendToClaude(browser, problems) {
  const r = {};
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push("page error (send to claude): " + e.message));
  const btn = page.locator("[data-send]");
  const msg = () => page.locator("[data-send-msg]").evaluate((el) => (el.hidden ? "" : el.textContent));
  const state = async () => ({ hidden: await btn.isHidden(), disabled: await btn.isDisabled(), msg: await msg() });
  await page.goto(file);
  await page.waitForTimeout(150);
  r.absent_hidden = await btn.isHidden();
  if (!r.absent_hidden) problems.push("Send to Claude shows on a page with no runtime");
  await page.addInitScript(installRuntime, { can: "no_session" });
  await page.reload();
  await page.waitForTimeout(250);
  r.no_session = await state();
  if (r.no_session.hidden || !r.no_session.disabled) problems.push("Send to Claude is not shown disabled when no session listens");
  // The session comes back while the page sits in the background: shown again, re-checked.
  await page.evaluate(() => {
    window.__can = "available";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(100);
  // A session is listening but nothing is answered yet: still off, with the one-line reason.
  r.nothing_answered = await state();
  if (!r.nothing_answered.disabled) problems.push("Send to Claude is on with nothing answered");
  // Answer something while the store holds the write: the send must wait for Saved.
  await page.evaluate(() => { window.__dbMode = "hold"; });
  const radio = page.locator("input[type=radio]").first();
  let answeredId = "";
  if (await radio.count()) { answeredId = String(await radio.getAttribute("name")).split("::")[0]; await radio.check(); }
  else if (await page.locator(".rp-btn").count()) {
    answeredId = await page.locator(".rp-btn").first().evaluate((b) => b.closest(".rp-item").dataset.id);
    await page.locator(".rp-btn").first().click();
  } else if (await page.locator("[data-tick]").count()) {
    answeredId = await page.locator("[data-tick]").first().getAttribute("data-tick");
    await page.locator("[data-tick]").first().check();
  } else if (await page.locator('.rp-set-seg-b[aria-pressed="false"]:visible').count()) {
    const seg = page.locator('.rp-set-seg-b[aria-pressed="false"]:visible').first();
    answeredId = await seg.evaluate((b) => b.closest("[data-set-row]").dataset.setRow);
    await seg.click();
  }
  await page.waitForTimeout(100);
  r.available = await state();
  if (r.available.disabled) problems.push("Send to Claude stayed disabled after the session became available and something was answered");
  await btn.click();
  await page.waitForTimeout(400);
  r.sent_while_saving = await page.evaluate(() => window.__sent.length);
  if (r.sent_while_saving) problems.push("Send to Claude sent before the answers were saved");
  await page.evaluate(() => { window.__dbMode = "ok"; window.__release(); });
  await page.waitForTimeout(400);
  const sent = await page.evaluate(() => window.__sent);
  const S = await page.evaluate(() => JSON.parse(document.getElementById("rp-spec").textContent));
  const last = sent[sent.length - 1] || {};
  r.sync_at_send = last.sync || "";
  r.text = last.text || "";
  r.text_bytes = Buffer.byteLength(r.text, "utf8");
  r.text_has_answered_id = !!answeredId && new RegExp("answered [^(]*\\b" + answeredId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).test(r.text);
  if (answeredId && !r.text_has_answered_id) problems.push(`Send to Claude text does not name the answered card ${answeredId}`);
  r.sent_msg = await msg();
  if (sent.length !== 1) problems.push(`Send to Claude called sendToClaude ${sent.length} times for one tap`);
  if (r.text_bytes >= 4096) problems.push("Send to Claude text is over 4 KiB");
  if (!r.text.includes(S.version || S.page_version)) problems.push("Send to Claude text does not name the page version");
  if (!r.sent_msg.startsWith("Sent.")) problems.push('Send to Claude did not say "Sent" after the send resolved');
  // Errors: consent keeps the button; claude_unavailable says nothing was sent.
  await page.evaluate(() => { window.__sendErr = "consent_required"; });
  await btn.click();
  await page.waitForTimeout(300);
  r.consent = await state();
  if (r.consent.disabled) problems.push("Send to Claude stayed disabled after consent_required");
  await page.evaluate(() => { window.__sendErr = "claude_unavailable"; });
  await btn.click();
  await page.waitForTimeout(300);
  r.unavailable_msg = await msg();
  // The next load: a newer version means Claude picked it up; the same one, long after, does not.
  await page.evaluate(() => {
    const S = JSON.parse(document.getElementById("rp-spec").textContent);
    localStorage.setItem(S.key + ":sent", JSON.stringify({ sentAt: new Date(Date.now() - 60000).toISOString(), fromVersion: "older" }));
  });
  await page.reload();
  await page.waitForTimeout(250);
  r.picked_up = await msg();
  if (!r.picked_up.startsWith("Claude picked up your answers")) problems.push("no pickup line after Claude republished");
  await page.evaluate(() => {
    const S = JSON.parse(document.getElementById("rp-spec").textContent);
    localStorage.setItem(S.key + ":sent", JSON.stringify({ sentAt: new Date(Date.now() - 6 * 60000).toISOString(), fromVersion: S.page_version }));
  });
  await page.reload();
  await page.waitForTimeout(250);
  r.not_picked_up = await msg();
  if (!r.not_picked_up.startsWith("Not picked up yet")) problems.push('no "Not picked up yet" line five minutes after a send');
  for (const w of [1280, 390]) {
    await page.setViewportSize({ width: w, height: 900 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (over > 0) problems.push(`with Send to Claude shown, the page scrolls sideways by ${over}px at ${w}px wide`);
  }
  await ctx.close();
  return r;
}

(async () => {
  const problems = [];
  const browser = await launchChromium(chromium, process.env);
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.on("pageerror", (e) => problems.push("page error: " + e.message));
  page.on("console", (m) => { if (m.type() === "error") problems.push("console error: " + m.text()); });
  await page.addInitScript(() => {
    window.__copied = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: (t) => { window.__copied.push(t); return Promise.resolve(); } },
    });
  });
  await page.goto(file);
  const S = await page.evaluate(() => JSON.parse(document.getElementById("rp-spec").textContent));
  const out = { mode: S.mode };

  const items = (kind) => S.sections.filter((s) => s.kind === kind).flatMap((s) => s.items.map((it) => [s, it]));
  if (S.mode === "review") {
    const all = items("review");
    out.items = await page.locator(".rp-item").count();
    if (out.items !== all.length) problems.push(`rendered ${out.items} items, spec has ${all.length}`);
    const [sec, first] = all[0] || [];
    if (first) {
      const card = page.locator(`.rp-item[data-id="${first.id}"]`);
      if (first.variants.length > 1) {
        const v = first.variants[first.variants.length - 1].key;
        await card.locator(`.rp-variant[data-variant="${v}"]`).click();
        if ((await card.locator(`.rp-variant[data-variant="${v}"]`).getAttribute("aria-pressed")) !== "true")
          problems.push("choosing a variant did not move the selection");
      }
      for (const b of sec.decisions.buttons) {
        await card.locator(`.rp-btn[data-choice="${b.state}"]`).click();
        if ((await card.getAttribute("data-state")) !== b.state) problems.push(`button ${b.state} did not set the state`);
        if (b.comment === "required" && !(await card.locator(".rp-comment").isVisible()))
          problems.push(`button ${b.state} did not open the comment box`);
      }
      await card.locator(".rp-comment textarea").fill("smoke comment");
      if (sec.decisions.mark_read) await card.locator("[data-read]").check();
    }
  } else if (S.mode === "questions" || S.mode === "session") {
    out.items = await page.locator("[data-qid], [data-qaid], [data-entry]").count();
    // Open questions first: the first thing in <main>, and visible without scrolling. Measured
    // as the page opens: answering scrolls the page, which hid a 96px gap on long pages and
    // reported it on short ones.
    if (items("questions").length) {
      const first = await page.evaluate(() => {
        const el = document.querySelector(".rp-main").firstElementChild;
        const bars = Array.from(document.querySelectorAll(".rp-projectbar, .rp-statusbar, .bar"));
        const barBottom = Math.max(0, ...bars.map((b) => b.getBoundingClientRect().bottom));
        return { cls: el ? el.className : "", top: el ? el.getBoundingClientRect().top : 1e9, barBottom };
      });
      if (!first.cls.includes("rp-kind-questions")) problems.push("open questions are not the first thing under the sticky bar");
      if (first.top - first.barBottom > 80) problems.push(`open questions start ${Math.round(first.top - first.barBottom)}px below the sticky bar`);
    }
    const firstOpt = page.locator(".q input[type=radio]").first();
    if (await firstOpt.count()) await firstOpt.check();
    const firstQa = page.locator(".qa input[type=radio]").first();
    if (await firstQa.count()) await firstQa.check();
    // a reader writes the note, then ticks: a read entry folds its note box away
    const note = page.locator("[data-note]").first();
    if (await note.count()) await note.fill("smoke note");
    const tick = page.locator("[data-tick]").first();
    if (await tick.count()) await tick.check();
    if (S.mode === "session" && !(await page.title()).startsWith(S.session)) problems.push("<title> does not lead with the session name");
  } else if (S.mode === "settings") {
    const rows = items("settings").map(([, it]) => it);
    out.items = await page.locator("[data-set-row]").count();
    if (out.items !== rows.length) problems.push(`rendered ${out.items} setting rows, spec has ${rows.length}`);
    const count = () => page.locator("[data-set-count]").innerText();
    // A refused value shows its reason under the field and stays out of the save bar.
    const num = rows.find((it) => it.type === "int");
    if (num) {
      await page.locator(`[data-set-nav="${num.group}"]`).click();
      const box = page.locator(`[data-set-row="${num.id}"] [data-set-in]`);
      await box.fill("not a number");
      const err = page.locator(`[data-set-row="${num.id}"] [data-set-err]`);
      if (!(await err.isVisible()) || !(await err.innerText()).trim()) problems.push(`a refused ${num.id} shows no reason under its field`);
      if (!(await count()).startsWith("No changes")) problems.push("a refused value went into the save bar");
      await box.fill(num.from);
    }
    // A good value typed into a text box shows in the save bar (and, below, in the export).
    const path = rows.find((it) => it.type === "path");
    if (path) {
      await page.locator(`[data-set-nav="${path.group}"]`).click();
      await page.locator(`[data-set-row="${path.id}"] [data-set-in]`).fill("smoke/" + path.from);
      await page.waitForTimeout(50);
      if (!(await page.locator("[data-set-list]").innerText()).includes(path.label)) problems.push("a change did not show in the save bar");
    }
  } else {
    out.items = await page.locator("[data-entry]").count();
    if (out.items !== items("log").length) problems.push(`rendered ${out.items} entries, spec has ${items("log").length}`);
    const note = page.locator("[data-note]").first();
    if (await note.count()) await note.fill("smoke note");
    const opt = page.locator(".rp-opts input[type=radio]").first();
    if (await opt.count()) await opt.check();
    const entry = page.locator("[data-entry]").first();
    const tick = page.locator("[data-tick]").first();
    if (await tick.count()) {
      const open = await entry.evaluate((c) => Array.from(c.querySelectorAll("[data-q]"))
        .some((g) => !g.querySelector("input:checked")));
      await tick.check();
      const folded = await entry.evaluate((c) => c.classList.contains("rp-is-read"));
      if (folded === open) problems.push(open ? "a read entry with an unanswered option folded away" : "a read entry did not fold");
      await tick.uncheck();
      if (await entry.evaluate((c) => c.classList.contains("rp-is-read"))) problems.push("unticking did not unfold the entry");
      await tick.check();
    }
    if (!(await page.title()).startsWith(S.session)) problems.push("<title> does not lead with the session name");
  }

  // No database here (a local file): the bar must not claim "Saved".
  if (!(await page.locator("[data-sync]").count())) problems.push("the bar has no sync indicator");
  else if (await page.locator("[data-sync]").isVisible()) problems.push("the sync indicator shows on a page with no database");

  await page.locator("[data-copy]").first().click();
  await page.waitForTimeout(100);
  const copied = await page.evaluate(() => window.__copied);
  out.export = copied[copied.length - 1] || "";
  if (!out.export) problems.push("Copy wrote nothing to the clipboard");
  if (S.mode === "review" && out.export.split("\n")[0] !== S.header) problems.push("export does not start with the page header");
  if (!out.export.includes("smoke")) problems.push("export is missing the typed comment or note");

  // Persistence: reload and export again; the text must survive.
  await page.reload();
  const again = await page.evaluate(() => window.rpExport());
  const strip = (t) => t.replace(/^(sent|exported):.*$/m, "");
  if (strip(again) !== strip(out.export)) problems.push("state did not survive a reload");

  // The fallback must appear, and "Copied" must not, when the clipboard refuses.
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true,
      value: { writeText: () => Promise.reject(new Error("blocked")) } });
  });
  await page.locator("[data-copy]").first().click();
  await page.waitForTimeout(100);
  if (!(await page.locator(".rp-fallback").isVisible())) problems.push("no text-box fallback when the clipboard fails");
  if (await page.locator(".rp-flash.on").count()) problems.push('showed "Copied" although the copy failed');

  out.broken_images = await page.$$eval("img", (els) => els.filter((i) => !i.complete || i.naturalWidth === 0).map((i) => i.src.slice(0, 80)));
  if (out.broken_images.length) problems.push(`${out.broken_images.length} image(s) did not load`);
  // Shared assets are copied into their attributes by a script; a blank one means it did not run.
  const unfilled = await page.$$eval("[data-rp-asset]", (els) => els.filter((el) => /^data:image\/gif/.test(el.getAttribute(el.getAttribute("data-rp-asset").split(" ")[0]) || "")).length);
  if (unfilled) problems.push(`${unfilled} shared image(s) were never filled in`);
  const blank = await page.$$eval("img", (els) => els.filter((i) => /^data:image\/gif;base64,R0lGODlhAQABAAAAACH5/.test(i.getAttribute("src") || "")).length);
  if (blank) problems.push(`${blank} <img> still show the blank placeholder`);
  // Older Safari cannot show WebP: every <picture> must end in an <img> it can show.
  out.pictures = await page.$$eval("picture", (els) => els.map((p) => {
    const img = p.querySelector("img");
    return { fallback: img ? (img.getAttribute("src") || "").slice(0, 16) : "", shown: img ? img.currentSrc.slice(0, 16) : "" };
  }));
  const noFallback = out.pictures.filter((p) => !/^data:image\/(png|jpeg)/.test(p.fallback)).length;
  if (noFallback) problems.push(`${noFallback} <picture>(s) have no PNG or JPEG <img> fallback`);
  const fonts = await page.evaluate(async () => { await document.fonts.ready; return [...document.fonts].filter((f) => f.status === "error").map((f) => f.family); });
  if (fonts.length) problems.push(`font(s) failed to load: ${fonts.join(", ")}`);
  // Rails run 1: a mockup's narrow cards broke "authenticat / ion" and only pr-qa noticed. Run
  // the capture's mid-word measure on every mockup, and name the item and variant it is in.
  const reviewItems = S.mode === "review" ? items("review").map(([, it]) => it) : [];
  const seenBreaks = new Set();
  out.mid_word = [];
  out.design_checks = [];
  out.notes = [];
  out.near_copies = [];
  // Every pair's score, flagged or not, so a session (and the tests) can see how far below the cut.
  out.layout_scores = [];
  // How wide each mockup's box is at 1280, so a session sizes its mockups to the box (or sets
  // the item's stack_variants) before it builds, not after rounds of captures.
  out.mockup_widths = [];
  if (reviewItems.length) {
    await page.setViewportSize({ width: 1280, height: 900 });
    const boxes = await page.evaluate(() => Array.from(document.querySelectorAll(".rp-item")).flatMap((item) => {
      const vb = Array.from(item.querySelectorAll(".rp-variant"));
      if (vb.length) {
        return vb.map((v) => ({ id: item.dataset.id, variant: v.dataset.variant,
          width: Math.round(v.querySelector(".rp-vbody").getBoundingClientRect().width) }));
      }
      const body = item.querySelector(".rp-body");
      return body ? [{ id: item.dataset.id, variant: null, width: Math.round(body.getBoundingClientRect().width) }] : [];
    }));
    for (const b of boxes) {
      const it = reviewItems.find((i) => i.id === b.id);
      out.mockup_widths.push({ item: it ? it.num : b.id, label: it ? it.label : "", variant: b.variant, width: b.width });
    }
  }
  if (S.mode === "settings") {
    out.small_taps = [];
    // the clipboard fallback above is still open over the page
    await page.locator(".rp-fallback [data-close]").click();
  }
  for (const w of [1280, 390]) {
    await page.setViewportSize({ width: w, height: 900 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (over > 0) problems.push(`page scrolls sideways by ${over}px at ${w}px wide`);
    if (S.mode === "settings") {
      // Every tap target in every group, at both widths: 44 by 44 at least.
      for (const [g] of S.sections[0].groups) {
        await page.locator(`[data-set-nav="${g}"]`).click();
        const small = await page.evaluate(() => Array.from(document.querySelectorAll("main button, main a[href], main input"))
          .filter((el) => el.offsetParent !== null)
          .map((el) => ({ el, r: el.getBoundingClientRect() }))
          .filter(({ r }) => r.width < 43.5 || r.height < 43.5)
          .map(({ el, r }) => `${(el.closest("[data-set-row]") || {}).dataset ? el.closest("[data-set-row]").dataset.setRow + " " : ""}${(el.textContent || el.getAttribute("placeholder") || el.tagName).trim()} ${Math.round(r.width)}x${Math.round(r.height)}`));
        for (const t of small) {
          if (out.small_taps.includes(`${t} at ${w}px`)) continue;
          out.small_taps.push(`${t} at ${w}px`);
          problems.push(`settings: tap target under 44x44: ${t} at ${w}px wide`);
        }
        const overG = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        if (overG > 0) problems.push(`settings group ${g} scrolls sideways by ${overG}px at ${w}px wide`);
      }
    }
    if (!reviewItems.length) continue;
    for (const b of await page.evaluate(midWordBreaks, { selector: ".rp-item .rp-body, .rp-item .rp-vbody", limit: 40 })) {
      const it = reviewItems.find((i) => i.id === b.where.item);
      const v = it && b.where.variant ? (it.variants || []).find((x) => x.key === b.where.variant) : null;
      const key = `${b.where.item}|${b.where.variant}|${b.word}`;
      if (seenBreaks.has(key)) continue;
      seenBreaks.add(key);
      out.mid_word.push({ item: it ? it.num : b.where.item, variant: b.where.variant, word: b.at, width: w });
      const where = `item ${it ? it.num : "?"}${it ? ` (${it.label})` : ""}${v ? `, ${v.label}` : ""}`;
      problems.push(`${where}: "${b.at}" breaks mid-word at ${w}px wide; widen the box, shrink the type or use fewer columns`);
    }
    // Contrast, tap targets, line length and edges on each mockup, by item and variant. A one-option
    // item's proposal is the .rp-mockup inside its body ("Proposed"); the page's own labels are not.
    // Unmeasured text and off-scale type sizes are notes, never problem lines. Design reviews only:
    // a style guide's or photo picker's options hold deliberately small or low-contrast examples.
    for (const it of reviewItems) {
      // A Refine change has no mockup: it is measured inside the base's frames, and never for near-copies.
      if (it.refine) continue;
      const sigs = [];
      const item = `.rp-item[data-id=${JSON.stringify(it.id)}]`;
      const oneOption = !(it.variants || []).length;
      const boxes = !oneOption
        ? it.variants.map((v) => [v.key, v.label, `${item} .rp-variant[data-variant=${JSON.stringify(v.key)}] .rp-vbody`])
        : [["proposed", "Proposed", `${item} .rp-body .rp-mockup`]];
      for (const [key, name, sel] of boxes) {
        if (!(await page.locator(sel).count())) {
          // A capture item needs no mockup; any other one-option design-review item without one is
          // never checked, which must not read as clean.
          if (oneOption && it.design_review && w === 1280 && it.category !== "capture")
            out.notes.push(`item ${it.num}: no .rp-mockup, design checks skipped`);
          continue;
        }
        if (w === 1280) sigs.push([key, name, await layoutSignature(page, sel)]);
        if (!it.design_review) continue;
        const d = await designChecks(page, sel, { width: w, beforeFontSizes: it.before_font_sizes || [] });
        out.design_checks.push({ item: it.num, variant: key, width: w, ...d });
        const where = `item ${it.num} (${it.label}), ${name}`;
        const lines = designLines(where, d, w);
        problems.push(...lines.problems);
        out.notes.push(...lines.notes);
      }
      // Near-copies, measured once at 1280: each pair of options, then each option against the
      // page's own section (`before_sections`, when the item carries it).
      // The pair check is for design reviews only: a style guide's options differ by size and a photo picker's are pictures.
      const near = (a, an, b, bn, sa, sb) => {
        if (b !== "before" && !it.design_review) return;
        const score = Math.round(similarity(sa, sb) * 100) / 100;
        out.layout_scores.push({ item: it.num, a, b, score });
        if (score < NEAR_COPY) return;
        out.near_copies.push({ item: it.num, a, b, score });
        const line = `item ${it.num} (${it.label}): ${an} and ${bn} are near-copies (${score.toFixed(2)})`;
        // A one-option fix (no variants, or exactly one) keeps the page's layout by design:
        // a note, and the Reason says what changed (Rulings 26 and 30).
        if ((it.variants || []).length <= 1) out.notes.push(`${line}; expected for a one-option fix: say what changed in the Reason`);
        else problems.push(line);
      };
      for (let i = 0; i < sigs.length; i++) {
        for (let j = i + 1; j < sigs.length; j++) near(sigs[i][0], sigs[i][1], sigs[j][0], sigs[j][1], sigs[i][2], sigs[j][2]);
      }
      if (it.before_sections) {
        const before = signatureFromSection(it.before_sections);
        for (const [key, name, sig] of sigs) near(key, name, "before", "the current page", sig, before);
      }
    }
  }
  if (S.mode === "review") {
    const r = await refineChecks(browser, page, S, problems, out.notes);
    if (r) out.refine = r;
  }
  out.send_to_claude = await sendToClaude(browser, problems);
  await browser.close();
  out.problems = problems;
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ problems: ["smoke crashed: " + e.message] })); process.exit(1); });
