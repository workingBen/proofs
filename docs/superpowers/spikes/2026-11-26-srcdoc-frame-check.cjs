// Repeatable file:// check for the srcdoc frame spike.
// Usage: node 2026-11-26-srcdoc-frame-check.cjs [playwright package dir]
const path = require("path"), os = require("os");
const pw = process.argv[2] || path.join(os.homedir(), ".cache/proofs-playwright/node_modules/playwright");
const { chromium } = require(pw);
const { launchChromium } = require("../../../shared/review_page/launch.cjs");
(async () => {
  const browser = await launchChromium(chromium, process.env);
  const page = await (await browser.newContext({ viewport: { width: 390, height: 800 } })).newPage();
  await page.goto("file://" + path.resolve(__dirname, "2026-11-26-srcdoc-frame.html"));
  await page.waitForFunction(() => document.getElementById("r390"));
  const read = () => page.evaluate(() => ({
    r1280: document.getElementById("r1280").textContent, r390: document.getElementById("r390").textContent,
    checks: [...document.querySelectorAll("#checks .report")].map((e) => e.textContent),
    scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth }));
  const before = await read();
  await page.click("#toggle"); const after = await read();
  await page.click("#toggle"); const back = await read();
  const show = (n, s) => { console.log("--- " + n); console.log(s.r1280); console.log(s.r390); s.checks.forEach((c) => console.log(c)); };
  show("before toggle", before); show("after toggle", after); show("toggled back", back);
  const all = [before, after, back].flatMap((s) => s.checks);
  const bad = all.filter((c) => !c.startsWith("PASS"));
  console.log(bad.length ? "RESULT: FAIL (" + bad.length + ")" : "RESULT: PASS (" + all.length + " checks)");
  await browser.close();
  process.exit(bad.length ? 1 : 0);
})();
