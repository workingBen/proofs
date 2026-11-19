/* Review page engine (proofs, shared/review_page). Built into every page by
   review_page.py; do not hand-edit a built page's copy. The export functions
   are pure so the tests can run them under plain node. */
(function () {
  "use strict";

  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function localStamp(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function utcStamp(d) {
    return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()) +
      "T" + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + "Z";
  }
  function trimmed(s) { return String(s || "").trim(); }
  function noteLines(prefix, s) {
    var t = trimmed(s);
    return t ? t.split("\n").map(function (l) { return prefix + l; }) : [];
  }
  function buttonFor(S, state) {
    return S.decisions.buttons.filter(function (b) { return b.state === state; })[0];
  }
  function variantOf(item, key) {
    var vs = item.variants || [];
    return vs.filter(function (v) { return v.key === key; })[0] || vs.filter(function (v) { return v.key === item.selected; })[0] || vs[0];
  }

  function reviewLine(S, item, rec) {
    var D = S.decisions, tag;
    if (!rec.s) {
      if (D.pending === null || D.pending === undefined) return null;
      tag = D.pending;
    } else {
      var b = buttonFor(S, rec.s);
      if (!b) return null;
      var hasV = (item.variants || []).length > 0;
      tag = hasV && b.export_variant ? b.export_variant : b.export;
      if (rec.s === "deny" && rec.w && D.works_as_designed) tag = "DENY (Works as Designed)";
      if (hasV) {
        var v = variantOf(item, rec.v);
        tag = tag.replace("{sel}", v.label + (v.name ? ", " + v.name : ""));
      }
    }
    var line = item.num + ". " + item.label + " — " + tag;
    if (rec.r) line += " — READ";
    var c = trimmed(rec.c).replace(/\s*\n\s*/g, " ");
    if (c) line += " — COMMENT: " + c;
    return line;
  }

  function reviewExport(S, st) {
    var lines = [S.header];
    S.items.forEach(function (item) {
      var l = reviewLine(S, item, (st.items || {})[item.id] || {});
      if (l !== null) lines.push(l);
    });
    return lines.join("\n");
  }

  function questionsExport(S, st, now) {
    var ans = st.ans || {}, notes = st.notes || {};
    var lines = ["[" + S.format + " — answers]", "project: " + S.project, "stream:  " + S.stream,
      "round:   " + S.round, "artifact: " + S.artifact, "sent:    " + utcStamp(now), ""];
    (S.questions || []).forEach(function (q) {
      lines.push("Q " + q.qid + " (raised r" + q.round + ") | " + q.ask);
      lines.push("  -> " + (ans[q.qid] || "(UNANSWERED)"));
      lines.push.apply(lines, noteLines("  note: ", notes[q.qid]));
      lines.push("");
    });
    if ((S.qa || []).length) {
      lines.push("--- QA results ---", "");
      S.qa.forEach(function (c) {
        lines.push("QA " + c.qaid + " | " + c.check);
        lines.push("  -> " + (ans[c.qaid] || "(NOT CHECKED)"));
        lines.push.apply(lines, noteLines("  note: ", notes[c.qaid]));
        lines.push("");
      });
    }
    return lines.join("\n").replace(/\n+$/, "\n");
  }

  function logExport(S, st, now) {
    var read = st.read || {}, ans = st.ans || {}, notes = st.notes || {};
    var lines = ["WORKING LOG — my replies", "project: " + S.project, "session: " + S.session];
    if (S.repo) lines.push("repo: " + S.repo);
    (S.details || []).forEach(function (kv) { lines.push(kv[0] + ": " + kv[1]); });
    lines.push("exported: " + localStamp(now), "");
    S.entries.forEach(function (e) {
      lines.push(e.id + "  [" + (read[e.id] ? "read" : "unread") + "]  " + e.title);
      e.groups.forEach(function (q) {
        var a = ans[e.id + "::" + q] || "(unanswered)";
        lines.push("      answer" + (e.groups.length > 1 ? " (" + q + ")" : "") + ": " + a);
      });
      lines.push.apply(lines, noteLines("      note: ", notes[e.id]));
    });
    var extra = trimmed(st.extra);
    if (extra) lines.push("", "anything else:", extra);
    return lines.join("\n") + "\n";
  }

  function exportText(S, st, now) {
    now = now || new Date();
    if (S.mode === "review") return reviewExport(S, st);
    if (S.mode === "questions") return questionsExport(S, st, now);
    return logExport(S, st, now);
  }

  if (typeof module !== "undefined" && module.exports) module.exports = { exportText: exportText };
  if (typeof document === "undefined") return;

  /* ------------------------------------------------------------ the page */
  var S = JSON.parse(document.getElementById("rp-spec").textContent);
  var st = {};
  try { st = JSON.parse(localStorage.getItem(S.key) || "{}") || {}; } catch (e) { st = {}; }
  function save() { try { localStorage.setItem(S.key, JSON.stringify(st)); } catch (e) { /* private window */ } }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function one(sel, root) { return (root || document).querySelector(sel); }

  var flashTimer;
  function flash() {
    var f = one(".rp-flash");
    f.classList.add("on");
    clearTimeout(flashTimer);
    flashTimer = setTimeout(function () { f.classList.remove("on"); }, 2200);
  }
  function fallback(text) {
    var box = one(".rp-fallback"), ta = one("textarea", box);
    ta.value = text;
    box.hidden = false;
    ta.focus();
    ta.select();
  }
  function copyText(text) {
    window.__rpLastExport = text;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(flash, function () { fallback(text); });
        return;
      }
    } catch (e) { /* fall through */ }
    fallback(text);
  }
  one(".rp-fallback [data-close]").addEventListener("click", function () { one(".rp-fallback").hidden = true; });
  all("[data-copy]").forEach(function (b) {
    b.addEventListener("click", function () { copyText(exportText(S, st, new Date())); });
  });
  window.rpExport = function () { return exportText(S, st, new Date()); };

  /* ------------------------------------------------------------ review */
  function setupReview() {
    st.items = st.items || {};
    var D = S.decisions;
    function rec(id) { return (st.items[id] = st.items[id] || {}); }
    function itemSpec(id) { return S.items.filter(function (i) { return i.id === id; })[0]; }

    function paintItem(card) {
      var id = card.dataset.id, r = rec(id), it = itemSpec(id);
      all(".rp-btn", card).forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.choice === r.s)); });
      var v = (it.variants || []).length ? variantOf(it, r.v).key : null;
      all(".rp-variant", card).forEach(function (el) { el.setAttribute("aria-pressed", String(el.dataset.variant === v)); });
      var b = r.s ? buttonFor(S, r.s) : null;
      card.dataset.state = r.s || "";
      one("[data-pill]", card).textContent = b ? b.label.replace(/^[^A-Za-z]+/, "") : "Pending";
      var box = one(".rp-comment", card), ta = one("textarea", box);
      if (ta.value !== (r.c || "")) ta.value = r.c || "";
      if (!D.comment_always) box.hidden = !((b && b.comment === "required") || trimmed(r.c));
      var wad = one(".rp-wad", card);
      if (wad) { wad.hidden = r.s !== "deny"; one("input", wad).checked = !!r.w; }
      var read = one("[data-read]", card);
      if (read) { read.checked = !!r.r; card.classList.toggle("rp-is-read", !!r.r); }
    }
    function paintBar() {
      var total = S.items.length, counts = {}, done = 0;
      S.items.forEach(function (it) {
        var s = rec(it.id).s;
        if (s) { done++; counts[s] = (counts[s] || 0) + 1; }
      });
      var parts = ["<b>" + done + "</b> of " + total + " reviewed"];
      D.buttons.forEach(function (b) {
        parts.push('<span class="rp-tally-st rp-st-' + b.state + '">' + b.label.replace(/^[^A-Za-z]+/, "") + " " + (counts[b.state] || 0) + "</span>");
      });
      one("#rp-tally").innerHTML = parts.join(" · ");
      var prog = one(".rp-progress");
      if (prog) {
        prog.innerHTML = D.buttons.map(function (b) {
          return '<span class="rp-st-' + b.state + '" style="flex:' + (counts[b.state] || 0) + '"></span>';
        }).join("") + '<span class="rp-prog-rest" style="flex:' + (total - done) + '"></span>';
      }
      all("[data-count]").forEach(function (el) {
        var c = el.dataset.count;
        var open = S.items.filter(function (it) { return (!c || it.category === c) && !rec(it.id).s; }).length;
        el.textContent = "· " + open + " open";
      });
    }
    function paint() { all(".rp-item").forEach(paintItem); paintBar(); }

    all(".rp-item").forEach(function (card) {
      var id = card.dataset.id;
      all(".rp-btn", card).forEach(function (b) {
        b.addEventListener("click", function () {
          var r = rec(id);
          r.s = r.s === b.dataset.choice ? null : b.dataset.choice;
          save(); paint();
          var bt = r.s ? buttonFor(S, r.s) : null;
          if (bt && bt.comment === "required") one("textarea", card).focus();
        });
      });
      all(".rp-variant", card).forEach(function (el) {
        function pick() { rec(id).v = el.dataset.variant; save(); paint(); }
        el.addEventListener("click", function (e) { if (!e.target.closest("a,input,textarea,select")) pick(); });
        el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
      });
      one("textarea", card).addEventListener("input", function (e) { rec(id).c = e.target.value; save(); paintBar(); });
      var wad = one("[data-wad]", card);
      if (wad) wad.addEventListener("change", function () { rec(id).w = wad.checked; save(); });
      var read = one("[data-read]", card);
      if (read) read.addEventListener("change", function () { rec(id).r = read.checked; save(); paint(); });
    });
    all("[data-filter]").forEach(function (b) {
      b.addEventListener("click", function () {
        var c = b.dataset.filter;
        all("[data-filter]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        all(".rp-item").forEach(function (card) { card.hidden = !!c && card.dataset.category !== c; });
        all(".rp-section").forEach(function (sec) {
          var cards = all(".rp-item", sec);
          sec.hidden = cards.length > 0 && cards.every(function (x) { return x.hidden; });
        });
      });
    });
    all("[data-preview-set]").forEach(function (b) {
      b.addEventListener("click", function () {
        one(".rp-main").dataset.preview = b.dataset.previewSet;
        all("[data-preview-set]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
      });
    });
    paint();
  }

  /* ------------------------------------------------------------ questions */
  function setupQuestions() {
    st.ans = st.ans || {}; st.notes = st.notes || {};
    function restore() {
      all("input[type=radio]").forEach(function (r) { r.checked = st.ans[r.name] === r.value; });
      all("[data-note]").forEach(function (t) { t.value = st.notes[t.dataset.note] || ""; });
    }
    function paint() {
      function tally(sel) {
        var cards = all(sel);
        return { total: cards.length, done: cards.filter(function (c) { return st.ans[c.dataset.qid || c.dataset.qaid]; }).length };
      }
      var q = tally("[data-qid]"), qa = tally("[data-qaid]"), parts = [];
      if (q.total) parts.push(q.done === q.total ? "all " + q.total + " answered" : "<b>" + q.done + "</b> of " + q.total + " answered");
      if (qa.total) parts.push(qa.done === qa.total ? "QA all " + qa.total + " checked" : "QA <b>" + qa.done + "</b> of " + qa.total);
      one("#rp-tally").innerHTML = parts.join(" · ");
      all(".q").forEach(function (c) { c.classList.toggle("answered", !!st.ans[c.dataset.qid]); });
      all(".qa").forEach(function (c) {
        var v = st.ans[c.dataset.qaid];
        c.classList.toggle("pass", v === "PASS");
        c.classList.toggle("fail", v === "FAIL");
        c.classList.toggle("skip", v === "COULDN'T TEST");
      });
    }
    document.addEventListener("change", function (e) {
      if (e.target.type === "radio") { st.ans[e.target.name] = e.target.value; save(); paint(); }
    });
    document.addEventListener("input", function (e) {
      if (e.target.dataset && e.target.dataset.note) { st.notes[e.target.dataset.note] = e.target.value; save(); }
    });
    one("#rp-clear").addEventListener("click", function () {
      if (!window.confirm("Clear every answer and note on this page?")) return;
      st = { ans: {}, notes: {} }; save(); restore(); paint();
    });
    restore(); paint();
  }

  /* ------------------------------------------------------------ log */
  function setupLog() {
    st.read = st.read || {}; st.ans = st.ans || {}; st.notes = st.notes || {};
    function paint() {
      var cards = all("[data-entry]"), n = 0;
      cards.forEach(function (c) {
        var r = !!st.read[c.dataset.entry];
        if (r) n++;
        c.classList.toggle("rp-is-read", r);
      });
      one("#rp-tally").innerHTML = "<b>" + n + "</b> / " + cards.length + " read";
    }
    all("input[type=radio]").forEach(function (r) { r.checked = st.ans[r.name] === r.value; });
    all("[data-note]").forEach(function (t) { t.value = st.notes[t.dataset.note] || ""; });
    all("[data-tick]").forEach(function (t) { t.checked = !!st.read[t.dataset.tick]; });
    var extra = one("[data-extra]");
    if (extra) extra.value = st.extra || "";
    document.addEventListener("change", function (e) {
      var t = e.target;
      if (t.type === "radio") st.ans[t.name] = t.value;
      else if (t.dataset && t.dataset.tick) st.read[t.dataset.tick] = t.checked;
      else return;
      save(); paint();
    });
    document.addEventListener("input", function (e) {
      var t = e.target;
      if (t.dataset && t.dataset.note) st.notes[t.dataset.note] = t.value;
      else if (t.dataset && t.dataset.extra !== undefined) st.extra = t.value;
      else return;
      save();
    });
    paint();
  }

  ({ review: setupReview, questions: setupQuestions, log: setupLog })[S.mode]();
})();
