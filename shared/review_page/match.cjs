// The built page against the Refine preview (spec §7): after the picks are built into the real
// templates and the page is captured again, each of that capture's shots at 1280 and 390 is
// compared with the base shot with the picked changes on, by fidelity.cjs comparePicks.
// Usage: node match.cjs <playwright package dir> <page.html> <picks, such as 1,3> <shots dir>
// Prints one JSON line: { match, lines: [...], widths: { 1280: {...}, 390: {...} } }, or
// { error } when it cannot measure. Run through review_page.py --match-preview.
const fs = require("fs");
const path = require("path");
const { chromium } = require(process.argv[2]);
const { launchChromium } = require("./launch.cjs");
const { comparePicks, renderBase, shotNames, FIDELITY, MISSED_PICKS } = require("./fidelity.cjs");

const [pagePath, picksArg, shots] = process.argv.slice(3);

function fromPage(text) {
  const spec = text.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/);
  const prev = text.match(/<div class="rp-rc-preview" data-rc-preview="([^"]*)" data-rc-base="([^"]*)"/);
  if (!spec || !prev) return null;
  const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const id = unesc(prev[1]);
  const base = text.match(new RegExp(`<script type="application/json" id="rp-rc-base-${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}">([\\s\\S]*?)</script>`));
  if (!base) return null;
  const S = JSON.parse(spec[1]);
  const changes = S.sections.flatMap((s) => s.items || []).filter((i) => i.refine === id);
  return { id, baseRel: unesc(prev[2]), doc: JSON.parse(base[1]), changes };
}

// The capture's shot of the built page: the before shot's own name (the same page and state,
// captured again into another folder), the same with "before-" made "after-" (--evidence),
// else the one <name>-<width>.png in the folder that is not a full shot, a part or a logo.
function buildShot(baseRel, w) {
  const names = shotNames(baseRel, w);
  const tried = [...names, ...names.filter((n) => n.startsWith("before-")).map((n) => "after-" + n.slice(7))];
  for (const n of tried) if (fs.existsSync(path.join(shots, n))) return { file: path.join(shots, n), tried };
  const only = fs.readdirSync(shots).filter((n) => n.endsWith(`-${w}.png`) && !/-(full|logo|part-\d+)-/.test(n) && !/logo-\d+\.png$/.test(n));
  return { file: only.length === 1 ? path.join(shots, only[0]) : null, tried };
}

(async () => {
  const info = fromPage(fs.readFileSync(pagePath, "utf8"));
  if (!info) { console.log(JSON.stringify({ error: `${pagePath} has no Refine preview` })); return; }
  const nums = picksArg.split(",").map((n) => n.trim()).filter(Boolean);
  const unknown = nums.filter((n) => !info.changes.some((c) => c.num === n));
  if (unknown.length) {
    console.log(JSON.stringify({ error: `no change ${unknown.join(", ")} on this page (its changes are ${info.changes.map((c) => c.num).join(", ")})` }));
    return;
  }
  const on = info.changes.filter((c) => nums.includes(c.num));
  const which = `change${on.length > 1 ? "s" : ""} ${on.map((c) => c.num).join(", ")}`;
  const browser = await launchChromium(chromium, process.env);
  const out = { match: true, lines: [], widths: {} };
  for (const w of [1280, 390]) {
    const shot = buildShot(info.baseRel, w);
    if (!shot.file) {
      out.match = false;
      out.widths[w] = null;
      out.lines.push(`${w}: no shot of the built page in ${shots} (looked for ${shot.tried.join(", ")}, or one *-${w}.png)`);
      continue;
    }
    const baseShot = await renderBase(browser, info.doc, w, []);
    const preview = await renderBase(browser, info.doc, w, on.map((c) => c.id));
    const r = await comparePicks(baseShot, preview, shot.file);
    out.widths[w] = { ...r, build: shot.file };
    const bad = [];
    if (r.pixelRatio > FIDELITY.pixelRatio) bad.push(`the build differs from the preview of ${which} (pixel ratio ${r.pixelRatio.toFixed(3)}, over ${FIDELITY.pixelRatio})`);
    if (r.missed !== null && r.missed > MISSED_PICKS) bad.push(`${Math.round(r.missed * 100)}% of the pixels ${which} change are not as the preview shows them (over ${MISSED_PICKS * 100}%)`);
    if (bad.length) { out.match = false; out.lines.push(`${w}: ${bad.join("; ")}`); }
    else out.lines.push(`${w}: match: the build matches the preview of ${which} (pixel ratio ${r.pixelRatio.toFixed(3)}${r.missed === null ? ", the picks change nothing at this width" : `, ${Math.round(r.missed * 100)}% of the picks' pixels off`})`);
  }
  await browser.close();
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ error: "match crashed: " + (e && e.message) })); process.exit(1); });
