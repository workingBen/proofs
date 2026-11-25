// Click through a built review page in headless Chromium (or the installed Google Chrome) and report what broke.
// Usage: node smoke.cjs <playwright package dir> <page.html>
// Prints one JSON line: { mode, items, export, problems: [...] }. Exercises the
// first item of each kind the page's frame uses, and on question and session
// pages checks that open questions sit directly under the sticky bar; on review pages it
// also flags a word a mockup breaks mid-word, by item and variant. Run through
// review_page.py --smoke rather than directly.
const path = require("path");
const { chromium } = require(process.argv[2]);
const { launchChromium } = require("./launch.cjs");
const { midWordBreaks } = require("./midword.cjs");
const { designChecks } = require("./designchecks.cjs");
const { layoutSignature, signatureFromSection, similarity, NEAR_COPY } = require("./signature.cjs");
const file = "file://" + path.resolve(process.argv[3]);

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
  for (const w of [1280, 390]) {
    await page.setViewportSize({ width: w, height: 900 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (over > 0) problems.push(`page scrolls sideways by ${over}px at ${w}px wide`);
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
        if (d.contrast.length) problems.push(`${where}: ${d.contrast.length} text elements below AA contrast at ${w}px`);
        if (d.smallTargets.length) problems.push(`${where}: ${d.smallTargets.length} tap targets under 44x44 at ${w}px`);
        if (d.longLines.length) problems.push(`${where}: ${d.longLines.length} lines over 80 characters at ${w}px`);
        if (d.edges.length) problems.push(`${where}: ${d.edges.length} left edges 1 to 6px out of line at ${w}px`);
        if (d.clippedRows.length) problems.push(`${where}: ${d.clippedRows.length} row${d.clippedRows.length > 1 ? "s" : ""} cut at the right edge at ${w}px (${d.clippedRows.map((c) => `"${c.cut}" cut`).join("; ")})`);
        if (d.peekRows.length) out.notes.push(`${where}: ${d.peekRows.length} carousel${d.peekRows.length > 1 ? "s" : ""} show a partly visible card at ${w}px (${d.peekRows.map((c) => `"${c.cut || c.text}"`).join("; ")}); a swipe peek, check it is meant`);
        if (d.unmeasured.length) {
          const why = [...new Set(d.unmeasured.map((u) => u.reason.replace(/^contrast: not measured \((.*)\)$/, "$1")))];
          out.notes.push(`${where}: contrast not measured for ${d.unmeasured.length} text elements (${why.join("; ")}) at ${w}px`);
        }
        if (d.offScale.length) out.notes.push(`${where}: ${d.offScale.length} text sizes off the page's own scale at ${w}px (${d.offScale.map((o) => o.size + "px").join(", ")})`);
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
  await browser.close();
  out.problems = problems;
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ problems: ["smoke crashed: " + e.message] })); process.exit(1); });
