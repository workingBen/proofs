// Click through a built review page in headless Chromium and report what broke.
// Usage: node smoke.cjs <playwright package dir> <page.html>
// Prints one JSON line: { mode, items, export, problems: [...] }. Exercises the
// first item of each kind the page's frame uses, and on question and session
// pages checks that open questions sit directly under the sticky bar. Run through
// review_page.py --smoke rather than directly.
const path = require("path");
const { chromium } = require(process.argv[2]);
const file = "file://" + path.resolve(process.argv[3]);

(async () => {
  const problems = [];
  const browser = await chromium.launch();
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
    const firstOpt = page.locator(".q input[type=radio]").first();
    if (await firstOpt.count()) await firstOpt.check();
    const firstQa = page.locator(".qa input[type=radio]").first();
    if (await firstQa.count()) await firstQa.check();
    const tick = page.locator("[data-tick]").first();
    if (await tick.count()) await tick.check();
    const note = page.locator("[data-note]").first();
    if (await note.count()) await note.fill("smoke note");
    // Open questions first: the first thing in <main>, and visible without scrolling.
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
    if (S.mode === "session" && !(await page.title()).startsWith(S.session)) problems.push("<title> does not lead with the session name");
  } else {
    out.items = await page.locator("[data-entry]").count();
    if (out.items !== items("log").length) problems.push(`rendered ${out.items} entries, spec has ${items("log").length}`);
    const tick = page.locator("[data-tick]").first();
    if (await tick.count()) await tick.check();
    const opt = page.locator(".rp-opts input[type=radio]").first();
    if (await opt.count()) await opt.check();
    const note = page.locator("[data-note]").first();
    if (await note.count()) await note.fill("smoke note");
    if (!(await page.title()).startsWith(S.session)) problems.push("<title> does not lead with the session name");
  }

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
  for (const w of [1280, 390]) {
    await page.setViewportSize({ width: w, height: 900 });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (over > 0) problems.push(`page scrolls sideways by ${over}px at ${w}px wide`);
  }
  await browser.close();
  out.problems = problems;
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ problems: ["smoke crashed: " + e.message] })); process.exit(1); });
