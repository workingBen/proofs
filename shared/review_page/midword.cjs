// Words a browser broke across two lines in the middle ("authenticat|ion"). Shared by the
// visual-qa capture (the whole page) and the review page smoke check (each mockup), so
// design-review's mockups are held to the same check pr-qa runs on the built page.
//
// Runs in the page through page.evaluate, so it must stay self-contained: no closures,
// no requires. Arguments: { selector, limit }. Returns
// [{ word, at, where }] with `at` the word split at the break ("authenticat|ion") and
// `where` the nearest [data-variant] and [data-id] around it, when there are any.
//
// A break at a hyphen, dash or slash is a normal line break, not a mid-word one, so each
// run of four or more letters between those is a word of its own.
//
// Code (<pre>, <code>) is skipped unless it is told to break anywhere (`word-break:
// break-all` or `overflow-wrap: anywhere`): then a command can break mid-word like prose
// (Astro run 1: the quick-start `<pre>` with break-all split "--tem" / "plate" at 390).
function midWordBreaks({ selector = 'body', limit = 20 } = {}) {
  const out = [];
  const shown = (el) => {
    for (let a = el; a; a = a.parentElement) {
      const s = getComputedStyle(a);
      if (s.display === 'none' || s.visibility === 'hidden') return false;
    }
    return true;
  };
  for (const root of document.querySelectorAll(selector)) {
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (tw.nextNode() && out.length < limit) {
      const node = tw.currentNode;
      const el = node.parentElement;
      if (!el || el.closest('svg,textarea,script,style') || !shown(el)) continue;
      if (el.closest('code,pre')) {
        const cs = getComputedStyle(el);
        if (cs.wordBreak !== 'break-all' && cs.overflowWrap !== 'anywhere') continue;
      }
      const re = /[^\s\-‐-―\/]{4,}/g;
      let m;
      while ((m = re.exec(node.textContent)) && out.length < limit) {
        const range = document.createRange();
        range.setStart(node, m.index); range.setEnd(node, m.index + m[0].length);
        const rects = [...range.getClientRects()].filter((r) => r.width > 0);
        if (new Set(rects.map((r) => Math.round(r.top))).size < 2) continue;
        // Find the first letter that sits on a lower line than the word's first letter.
        let cut = 0;
        const top = (i) => { const r = document.createRange(); r.setStart(node, m.index + i); r.setEnd(node, m.index + i + 1);
          const b = r.getBoundingClientRect(); return Math.round(b.top); };
        const first = top(0);
        for (let i = 1; i < m[0].length; i++) { if (top(i) > first + 1) { cut = i; break; } }
        const variant = el.closest('[data-variant]');
        const item = el.closest('[data-id]');
        out.push({
          word: m[0].slice(0, 30),
          at: cut ? `${m[0].slice(0, cut)}|${m[0].slice(cut)}`.slice(0, 40) : m[0].slice(0, 30),
          where: { item: item ? item.getAttribute('data-id') : null, variant: variant ? variant.getAttribute('data-variant') : null },
        });
      }
    }
  }
  return out;
}

module.exports = { midWordBreaks };
