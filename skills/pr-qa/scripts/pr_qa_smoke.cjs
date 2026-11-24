// Click through a built pr-qa page in headless Chromium (or the installed Chrome)
// and report what broke.
// Usage: node pr_qa_smoke.cjs <playwright package dir> <page.html>
// Prints one JSON line: { ok, problems: [...] }. Run through
// `pr_qa_page.py --smoke PAGE` rather than directly.
const path = require("path");
const { chromium } = require(process.argv[2]);
const { launchChromium, HOW_TO } = require("../../../shared/review_page/launch.cjs");
const file = "file://" + path.resolve(process.argv[3]);

(async () => {
  const problems = [];
  let browser;
  try {
    browser = await launchChromium(chromium, process.env);
  } catch (e) {
    // A missing browser is not a page problem: exit 2 so the caller says so
    // instead of looping on a fix.
    const msg = String((e && e.message) || e);
    console.log(JSON.stringify({
      ok: false, launchFailed: true,
      problems: ["Browser could not start: " + msg + (msg.includes(HOW_TO) ? "" : "\n" + HOW_TO)],
    }));
    process.exit(2);
  }
  try {
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
    await page.waitForLoadState("load");
    await page.waitForTimeout(200);

    // Screenshots the builder expected and did not find (SvelteKit run 1: a 29 KB page with
    // no images passed). The builder lists each gap; one the meta entry gave a reason for is not.
    const gaps = await page.evaluate(() => (typeof DATA !== "undefined" && DATA.evidenceGaps) || []);
    for (const g of gaps) problems.push("screenshot gap: " + g);

    // Every image that has a source must have decoded.
    const broken = await page.evaluate(() =>
      Array.from(document.images).filter((i) => i.getAttribute("src") && !(i.complete && i.naturalWidth > 0))
        .map((i) => (i.getAttribute("src") || "").slice(0, 40)));
    if (broken.length) problems.push(`${broken.length} image(s) did not load (naturalWidth 0)`);

    // Each PR card: its decision radios can be checked.
    const cards = page.locator(".pr-card");
    const count = await cards.count();
    for (let i = 0; i < count; i++) {
      const card = cards.nth(i);
      const id = await card.getAttribute("id");
      const options = card.locator("label.decision-option");
      const n = await options.count();
      if (!n) { problems.push(`${id}: no decision radios`); continue; }
      for (let j = 0; j < n; j++) {
        await options.nth(j).click();
        if (!(await options.nth(j).locator("input[type=radio]").isChecked()))
          problems.push(`${id}: decision option ${j + 1} did not check`);
      }
    }

    // The copy button produces export text (clipboard stub, or the fallback box).
    if (count) {
      const button = page.locator("button[data-copy]");
      if (!(await button.count())) problems.push("no copy button");
      else {
        await button.click();
        const text = await page.evaluate(() => {
          const box = document.querySelector("textarea[data-copy-fallback]");
          return (window.__copied && window.__copied[0]) || (box && box.value) || "";
        });
        if (!text.trim()) problems.push("copy button produced no export text");
      }
    }

    // The page on a phone: any sideways scroll at 390, even a few pixels, is a problem (Astro
    // run 2: the page was 393 px wide at 390 and this check passed it). An emulated phone lays
    // a too-wide page out wider and zooms out, so take the wider of scrollWidth and innerWidth.
    const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    try {
      await phone.goto(file);
      await phone.waitForLoadState("load");
      await phone.waitForTimeout(200);
      const wide = await phone.evaluate(() => {
        const d = document.documentElement;
        const over = Math.max(d.scrollWidth, window.innerWidth) - 390;
        if (over <= 0) return null;
        let worst = null;
        for (const el of document.querySelectorAll("body *")) {
          const r = el.getBoundingClientRect();
          if (r.width <= 0 || r.right <= 390.5) continue;
          // Inside a box that scrolls or clips within the screen (the verdict table): not the cause.
          let boxed = false;
          for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
            if (getComputedStyle(a).overflowX !== "visible" && a.getBoundingClientRect().right <= 390.5) { boxed = true; break; }
          }
          if (boxed) continue;
          // The deepest element past the edge names the culprit, not the wrappers around it.
          if (!worst || worst.el.contains(el) || r.right > worst.right + 0.5) worst = { el, right: r.right };
        }
        const name = worst ? worst.el.tagName.toLowerCase() + (worst.el.className && typeof worst.el.className === "string"
          ? "." + worst.el.className.trim().split(/\s+/).join(".") : "") : "";
        return { over, name, text: worst ? (worst.el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40) : "" };
      });
      if (wide) {
        problems.push(`the page scrolls sideways at 390: ${wide.over}px past the screen`
          + (wide.name ? ` (widest: ${wide.name} "${wide.text}")` : "")
          + "; give long text overflow-wrap: anywhere, a flex child min-width: 0, or a table its own scroll box");
      }
    } finally {
      await phone.close();
    }
  } catch (e) {
    problems.push("smoke crashed: " + e.message);
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ ok: problems.length === 0, problems }));
  process.exit(problems.length ? 1 : 0);
})();
