// Repeatable file:// check for the srcdoc frame spike.
// Usage: node 2026-11-26-srcdoc-frame-check.cjs [playwright package dir]
const path = require("path"), os = require("os");
const pw = process.argv[2] || path.join(os.homedir(), ".cache/proofs-playwright/node_modules/playwright");
const { chromium } = require(pw);
const { launchChromium } = require("../../../shared/review_page/launch.cjs");
const URL_ = "file://" + path.resolve(__dirname, "2026-11-26-srcdoc-frame.html");
const G = "rgb(0, 128, 0)", R = "rgb(200, 0, 0)", P = "rgb(128, 0, 128)";
(async () => {
  const browser = await launchChromium(chromium, process.env);
  let fails = 0, n = 0;
  const eq = (name, got, want) => { n++; const ok = got === want; if (!ok) fails++; console.log((ok ? "PASS " : "FAIL ") + name + " (got " + got + ", want " + want + ")"); };
  try {
    const page = await (await browser.newContext({ viewport: { width: 390, height: 800 } })).newPage();
    await page.goto(URL_);
    await page.waitForFunction(() => document.getElementById("r390") && /rgb/.test(document.getElementById("r390").textContent), null, { timeout: 5000 });
    const colors = () => page.evaluate(() => [...document.querySelectorAll("#reports .report")].slice(0, 2).map((e) => e.textContent.replace(/.*color: /, "")));
    const pageChecks = () => page.evaluate(() => [...document.querySelectorAll("#checks .report")].map((e) => e.textContent));
    const step = async (name, sel, w, m) => {
      if (sel) await page.click(sel);
      const [a, b] = await colors(); eq(name + ": 1280", a, w); eq(name + ": 390", b, m);
      const bad = (await pageChecks()).filter((c) => !c.startsWith("PASS")); eq(name + ": page's own checks", bad.join("|"), "");
    };
    await step("initial", null, G, R);
    await step("toggle both on", "#toggle", P, P);
    await step("toggle both off", "#toggle", G, R);
    await step("1280 only on", "#t1280", P, R);
    await step("390 only on too", "#t390", P, P);
    await step("1280 only off", "#t1280", G, P);
    await step("390 only off", "#t390", G, R);
    await step("data-rc=c2 leaves originals", "#c2", G, R);
    await step('data-rc="c1 c2" is purple', "#c1c2", P, P);
    await step("c2 again", "#c2", G, R);
    eq("no sideways scroll", await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);

    // Not-loaded case: the 390 frame never gets its srcdoc; the page must show FAIL, not a blank.
    const p2 = await (await browser.newContext({ viewport: { width: 390, height: 800 } })).newPage();
    await p2.goto(URL_ + "?noload=390");
    const early = await p2.evaluate(() => document.querySelectorAll("#checks .report").length);
    eq("not-loaded: checks shown immediately (count > 0)", early > 0, true);
    await p2.waitForTimeout(2500);
    const lines = await p2.evaluate(() => [...document.querySelectorAll("#checks .report")].map((e) => e.textContent));
    eq("not-loaded: 390 reported FAIL after timeout", lines.includes("FAIL: 390 frame loaded"), true);
    eq("not-loaded: 1280 still reported PASS", lines.includes("PASS: 1280 frame loaded"), true);
  } finally { await browser.close(); }
  console.log(fails ? "RESULT: FAIL (" + fails + " of " + n + ")" : "RESULT: PASS (" + n + " checks)");
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error("RESULT: FAIL (script error) " + e.message); process.exit(1); });
