// Print a page's answers from its database rows as the same text its Copy button makes.
// Usage: node answers.cjs <page.html> <rows>
//   <rows> is the folder ArtifactData `list` wrote with `out_dir` (every .json file
//   below it is read), or one JSON file holding a document, an array of them, or an
//   object with a `documents` / `docs` array. A document may be the body itself or
//   wrapped as { data: <body> }. Rows for cards no longer on the page are ignored.
// Uses the engine built into the page, so the text matches that page's own export.
// Run through review_page.py --answers rather than directly.
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(process.argv[2], "utf8");
const spec = JSON.parse(html.match(/<script type="application\/json" id="rp-spec">([\s\S]*?)<\/script>/)[1]);
const code = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];
const m = { exports: {} };
new Function("module", code)(m);
const engine = m.exports;
if (!engine.applyAnswerDocs) {
  console.error("this page was built before answers were saved to its database; rebuild it, or use Copy");
  process.exit(2);
}

function jsonFiles(p) {
  if (fs.statSync(p).isDirectory()) {
    return fs.readdirSync(p).sort().flatMap((n) => jsonFiles(path.join(p, n)));
  }
  return p.endsWith(".json") ? [p] : [];
}
function unwrap(v) {
  if (Array.isArray(v)) return v.flatMap(unwrap);
  if (!v || typeof v !== "object") return [];
  if (Array.isArray(v.documents)) return unwrap(v.documents);
  if (Array.isArray(v.docs)) return unwrap(v.docs);
  if (v.data && typeof v.data === "object" && !Array.isArray(v.data) && v.data.kind) return [v.data];
  return v.kind ? [v] : [];
}

const docs = jsonFiles(process.argv[3]).flatMap((f) => unwrap(JSON.parse(fs.readFileSync(f, "utf8"))));
const st = engine.applyAnswerDocs(spec, {}, docs);
const newest = docs.map((d) => d.updated_at || "").sort().pop();
process.stdout.write(engine.exportText(spec, st, newest ? new Date(newest) : new Date()));
