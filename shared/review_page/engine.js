/* Review page engine (proofs, shared/review_page). Built into every page by
   review_page.py; do not hand-edit a built page's copy.

   A page is a frame (S.mode: review, questions, log or session: its chrome,
   tally and export header) around a list of sections (S.sections), each with a
   kind: review, questions, qa, log, or the read-only links and decided. Each kind renders its own items, keeps its own state under
   st.sec[<section id>], and contributes its own block to the export, so one
   page can mix kinds. The export functions are pure so the tests can run them
   under plain node. */
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
  function buttonFor(sec, state) {
    return sec.decisions.buttons.filter(function (b) { return b.state === state; })[0];
  }
  // The user's pick, else the spec's "selected", else the recommended variant, else the
  // first. Never blindly the first: Vue run 1's "Use Selected" exported a variant that was
  // not the recommended one because nobody had touched the picker.
  function variantOf(item, key) {
    var vs = item.variants || [];
    function by(f) { return vs.filter(f)[0]; }
    return by(function (v) { return v.key === key; }) || by(function (v) { return v.key === item.selected; }) ||
      by(function (v) { return v.recommended; }) || vs[0];
  }
  function secState(st, sec) {
    st.sec = st.sec || {};
    return (st.sec[sec.id] = st.sec[sec.id] || {});
  }

  /* ------------------------------------------------- export, per section kind */
  function reviewLine(sec, item, rec) {
    var D = sec.decisions, tag;
    if (!rec.s) {
      if (D.pending === null || D.pending === undefined) return null;
      tag = D.pending;
    } else {
      var b = buttonFor(sec, rec.s);
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

  var BLOCK = {
    review: function (sec, ss) {
      var recs = ss.items || {};
      return sec.items.map(function (it) { return reviewLine(sec, it, recs[it.id] || {}); })
        .filter(function (l) { return l !== null; });
    },
    questions: function (sec, ss) {
      var ans = ss.ans || {}, notes = ss.notes || {}, lines = [];
      sec.items.forEach(function (q) {
        lines.push("Q " + q.qid + " (raised r" + q.round + ") | " + q.ask);
        lines.push("  -> " + (ans[q.qid] || "(UNANSWERED)"));
        lines.push.apply(lines, noteLines("  note: ", notes[q.qid]));
        lines.push("");
      });
      return lines;
    },
    qa: function (sec, ss) {
      var ans = ss.ans || {}, notes = ss.notes || {};
      if (!sec.items.length) return [];
      var lines = ["--- QA results ---", ""];
      sec.items.forEach(function (c) {
        lines.push("QA " + c.qaid + " | " + c.check);
        lines.push("  -> " + (ans[c.qaid] || "(NOT CHECKED)"));
        lines.push.apply(lines, noteLines("  note: ", notes[c.qaid]));
        lines.push("");
      });
      return lines;
    },
    log: function (sec, ss) {
      var read = ss.read || {}, ans = ss.ans || {}, notes = ss.notes || {}, lines = [];
      sec.items.forEach(function (e) {
        lines.push(e.id + "  [" + (read[e.id] ? "read" : "unread") + "]  " + (e.when ? e.when + "  " : "") + e.title);
        e.groups.forEach(function (q) {
          lines.push("      answer" + (e.groups.length > 1 ? " (" + q + ")" : "") + ": " + (ans[e.id + "::" + q] || "(unanswered)"));
        });
        lines.push.apply(lines, noteLines("      note: ", notes[e.id]));
      });
      return lines;
    },
    links: function () { return []; },
    decided: function () { return []; }
  };

  function blocks(S, st) {
    var out = [];
    S.sections.forEach(function (sec) {
      out.push.apply(out, BLOCK[sec.kind](sec, ((st.sec || {})[sec.id]) || {}));
    });
    return out;
  }

  /* ------------------------------------------------- export, per frame */
  var FRAME = {
    review: function (S, st) { return [S.header].concat(blocks(S, st)).join("\n"); },
    questions: function (S, st, now) {
      var lines = ["[" + S.format + " — " + (S.verb || "answers") + "]", "project: " + S.project, "stream:  " + S.stream,
        "round:   " + S.round, "artifact: " + S.artifact, "sent:    " + utcStamp(now), ""];
      return lines.concat(blocks(S, st)).join("\n").replace(/\n+$/, "\n");
    },
    log: function (S, st, now) {
      var lines = ["WORKING LOG — my replies", "project: " + S.project, "session: " + S.session];
      if (S.repo) lines.push("repo: " + S.repo);
      (S.details || []).forEach(function (kv) { lines.push(kv[0] + ": " + kv[1]); });
      lines.push("exported: " + localStamp(now), "");
      lines = lines.concat(blocks(S, st));
      var extra = trimmed(st.extra);
      if (extra) lines.push("", "anything else:", extra);
      return lines.join("\n") + "\n";
    },
    // The session page: one export with a block per section that has one, in
    // page order (questions, QA, log), each under its own header.
    session: function (S, st, now) {
      var lines = ["WORKING LOG — my replies", "project: " + S.project, "session: " + S.session];
      if (S.repo) lines.push("repo: " + S.repo);
      if (S.artifact) lines.push("artifact: " + S.artifact);
      (S.details || []).forEach(function (kv) { lines.push(kv[0] + ": " + kv[1]); });
      lines.push("exported: " + localStamp(now));
      var HEAD = { questions: "--- Questions ---", log: "--- Log ---" };
      S.sections.forEach(function (sec) {
        var b = BLOCK[sec.kind](sec, ((st.sec || {})[sec.id]) || {});
        if (!b.length) return;
        lines.push("");
        if (HEAD[sec.kind]) lines.push(HEAD[sec.kind], "");
        lines.push.apply(lines, b);
      });
      var extra = trimmed(st.extra);
      if (extra) lines.push("", "anything else:", extra);
      return lines.join("\n").replace(/\n{3,}/g, "\n\n").replace(/\n+$/, "") + "\n";
    }
  };

  function exportText(S, st, now) { return FRAME[S.mode](S, st || {}, now || new Date()); }

  if (typeof module !== "undefined" && module.exports) module.exports = { exportText: exportText };
  if (typeof document === "undefined") return;

  /* ------------------------------------------------- the page */
  var S = JSON.parse(document.getElementById("rp-spec").textContent);
  var st = {};
  try { st = JSON.parse(localStorage.getItem(S.key) || "{}") || {}; } catch (e) { st = {}; }
  function save() { try { localStorage.setItem(S.key, JSON.stringify(st)); } catch (e) { /* private window */ } }
  function all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function one(sel, root) { return (root || document).querySelector(sel); }
  function rootOf(sec) { return one('[data-section="' + sec.id + '"]'); }
  function ofKind(kind) { return S.sections.filter(function (s) { return s.kind === kind; }); }

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

  /* ------------------------------------------------- tallies, per frame */
  function reviewStats() {
    var total = 0, done = 0, counts = {}, buttons = [];
    ofKind("review").forEach(function (sec) {
      var recs = secState(st, sec).items || {};
      sec.decisions.buttons.forEach(function (b) {
        if (!buttons.some(function (x) { return x.state === b.state; })) buttons.push(b);
      });
      sec.items.forEach(function (it) {
        total++;
        var s = (recs[it.id] || {}).s;
        if (s) { done++; counts[s] = (counts[s] || 0) + 1; }
      });
    });
    return { total: total, done: done, counts: counts, buttons: buttons };
  }
  function answered(kind) {
    var total = 0, done = 0;
    ofKind(kind).forEach(function (sec) {
      var ans = secState(st, sec).ans || {};
      sec.items.forEach(function (it) { total++; if (ans[it.qid || it.qaid]) done++; });
    });
    return { total: total, done: done };
  }
  var TALLY = {
    review: function () {
      var r = reviewStats();
      var parts = ["<b>" + r.done + "</b> of " + r.total + " reviewed"];
      r.buttons.forEach(function (b) {
        // The separator rides inside the span, so a phone can hide the counts without strays.
        parts.push('<span class="rp-tally-st rp-st-' + b.state + '"> · ' + b.label.replace(/^[^A-Za-z]+/, "") + " " + (r.counts[b.state] || 0) + "</span>");
      });
      one("#rp-tally").innerHTML = parts.join("");
      var prog = one(".rp-progress");
      if (prog) {
        prog.innerHTML = r.buttons.map(function (b) {
          return '<span class="rp-st-' + b.state + '" style="flex:' + (r.counts[b.state] || 0) + '"></span>';
        }).join("") + '<span class="rp-prog-rest" style="flex:' + (r.total - r.done) + '"></span>';
      }
      all("[data-count]").forEach(function (el) {
        var c = el.dataset.count, open = 0;
        ofKind("review").forEach(function (sec) {
          var recs = secState(st, sec).items || {};
          sec.items.forEach(function (it) { if ((!c || it.category === c) && !(recs[it.id] || {}).s) open++; });
        });
        el.textContent = "· " + open + " open";
      });
    },
    questions: function () {
      var q = answered("questions"), qa = answered("qa"), parts = [];
      if (q.total) parts.push(q.done === q.total ? "all " + q.total + " answered" : "<b>" + q.done + "</b> of " + q.total + " answered");
      if (qa.total) parts.push(qa.done === qa.total ? "QA all " + qa.total + " checked" : "QA <b>" + qa.done + "</b> of " + qa.total);
      one("#rp-tally").innerHTML = parts.join(" · ");
    },
    log: function () { one("#rp-tally").innerHTML = readTally(); },
    session: function () {
      var q = answered("questions"), qa = answered("qa"), parts = [];
      if (q.total) parts.push(q.done === q.total ? "all " + q.total + " answered" : "<b>" + q.done + "</b> of " + q.total + " answered");
      if (qa.total) parts.push(qa.done === qa.total ? "checks all " + qa.total + " done" : "checks <b>" + qa.done + "</b> of " + qa.total);
      if (ofKind("log").some(function (s) { return s.items.length; })) parts.push(readTally());
      one("#rp-tally").innerHTML = parts.join(" · ") || "nothing waiting on you";
    }
  };
  function readTally() {
    var n = 0, total = 0;
    ofKind("log").forEach(function (sec) {
      var read = secState(st, sec).read || {};
      sec.items.forEach(function (e) { total++; if (read[e.id]) n++; });
    });
    return "<b>" + n + "</b> / " + total + " read";
  }
  function tally() { TALLY[S.mode](); }

  /* ------------------------------------------------- behavior, per section kind */
  var SETUP = {
    review: function (sec, root, ss) {
      ss.items = ss.items || {};
      var D = sec.decisions;
      function rec(id) { return (ss.items[id] = ss.items[id] || {}); }
      function itemSpec(id) { return sec.items.filter(function (i) { return i.id === id; })[0]; }
      function paintItem(card) {
        var id = card.dataset.id, r = rec(id), it = itemSpec(id);
        all(".rp-btn", card).forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.choice === r.s)); });
        var v = (it.variants || []).length ? variantOf(it, r.v).key : null;
        all(".rp-variant", card).forEach(function (el) { el.setAttribute("aria-pressed", String(el.dataset.variant === v)); });
        var b = r.s ? buttonFor(sec, r.s) : null;
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
      function paint() { all(".rp-item", root).forEach(paintItem); tally(); }
      all(".rp-item", root).forEach(function (card) {
        var id = card.dataset.id;
        all(".rp-btn", card).forEach(function (b) {
          b.addEventListener("click", function () {
            var r = rec(id);
            r.s = r.s === b.dataset.choice ? null : b.dataset.choice;
            save(); paint();
            var bt = r.s ? buttonFor(sec, r.s) : null;
            if (bt && bt.comment === "required") one("textarea", card).focus();
          });
        });
        all(".rp-variant", card).forEach(function (el) {
          function pick() { rec(id).v = el.dataset.variant; save(); paint(); }
          el.addEventListener("click", function (e) { if (!e.target.closest("a,input,textarea,select")) pick(); });
          el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        });
        one("textarea", card).addEventListener("input", function (e) { rec(id).c = e.target.value; save(); tally(); });
        var wad = one("[data-wad]", card);
        if (wad) wad.addEventListener("change", function () { rec(id).w = wad.checked; save(); });
        var read = one("[data-read]", card);
        if (read) read.addEventListener("change", function () { rec(id).r = read.checked; save(); paint(); });
      });
      all(".rp-item", root).forEach(paintItem);
    },
    questions: answerable,
    qa: answerable,
    links: function () {},
    decided: function () {},
    log: function (sec, root, ss) {
      ss.read = ss.read || {}; ss.ans = ss.ans || {}; ss.notes = ss.notes || {};
      function paint() {
        var anyRead = false;
        all("[data-entry]", root).forEach(function (c) {
          // fold only when read AND every option group is answered: a folded card
          // must never hide a question still waiting on the reader
          var open = all("[data-q]", c).some(function (g) { return !ss.ans[c.dataset.entry + "::" + g.dataset.q]; });
          var r = !!ss.read[c.dataset.entry] && !open;
          c.classList.toggle("rp-is-read", r);
          anyRead = anyRead || r;
        });
        var head = one(".rp-read-head", root);
        if (head) head.hidden = !anyRead;
        tally();
      }
      all("input[type=radio]", root).forEach(function (r) { r.checked = ss.ans[r.name] === r.value; });
      all("[data-note]", root).forEach(function (t) { t.value = ss.notes[t.dataset.note] || ""; });
      all("[data-tick]", root).forEach(function (t) { t.checked = !!ss.read[t.dataset.tick]; });
      root.addEventListener("change", function (e) {
        var t = e.target;
        if (t.type === "radio") { ss.ans[t.name] = t.value; save(); paint(); return; }
        if (!(t.dataset && t.dataset.tick)) return;
        var card = t.closest("[data-entry]");
        var wasTop = card ? card.getBoundingClientRect().top : 0, wasY = window.scrollY;
        ss.read[t.dataset.tick] = t.checked;
        save(); paint();
        if (card) keepPlace(card, wasTop, wasY);
      });
      // A tick folds the entry and moves it to the Read list (flex order), which reflows the
      // page and used to leave the screen somewhere unrelated (found on a phone). After a
      // fold, bring the next unread entry's top to just under the sticky bars: the following
      // unread one, else the first unread one above. Nothing unread left: leave the scroll.
      // An entry that comes back (untick) keeps its top where it was.
      function barsBottom() {
        // The sticky bars' real height: it differs on a phone, where they wrap.
        var h = 0;
        // (Measured from the box, not read back from the computed style, which older iOS
        // Safari answers badly.) They stick at the top, so their bottom is their height.
        all(".rp-topbars").forEach(function (b) {
          h = Math.max(h, Math.max(0, b.getBoundingClientRect().top) + b.offsetHeight);
        });
        return h;
      }
      function keepPlace(card, wasTop, wasY) {
        if (!card.classList.contains("rp-is-read")) {
          window.scrollTo({ top: window.scrollY + card.getBoundingClientRect().top - wasTop, behavior: "instant" });
          return;
        }
        var entries = all("[data-entry]", root);
        var at = entries.indexOf(card);
        var unread = function (c) { return !c.classList.contains("rp-is-read"); };
        var next = entries.slice(at + 1).filter(unread)[0] || entries.slice(0, at).filter(unread)[0];
        if (!next) { window.scrollTo({ top: wasY, behavior: "instant" }); return; }
        var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        window.scrollTo({ top: window.scrollY + next.getBoundingClientRect().top - barsBottom() - 6,
                          behavior: reduce ? "instant" : "smooth" });
      }
      root.addEventListener("input", function (e) {
        if (e.target.dataset && e.target.dataset.note) { ss.notes[e.target.dataset.note] = e.target.value; save(); }
      });
      paint();
    }
  };

  // questions and qa: radio answers plus a note per item, keyed by qid / qaid.
  function answerable(sec, root, ss) {
    ss.ans = ss.ans || {}; ss.notes = ss.notes || {};
    function restore() {
      all("input[type=radio]", root).forEach(function (r) { r.checked = ss.ans[r.name] === r.value; });
      all("[data-note]", root).forEach(function (t) { t.value = ss.notes[t.dataset.note] || ""; });
    }
    function paint() {
      all(".q", root).forEach(function (c) { c.classList.toggle("answered", !!ss.ans[c.dataset.qid]); });
      all(".qa", root).forEach(function (c) {
        var v = ss.ans[c.dataset.qaid];
        c.classList.toggle("pass", v === "PASS");
        c.classList.toggle("fail", v === "FAIL");
        c.classList.toggle("skip", v === "COULDN'T TEST");
      });
      tally();
    }
    root.addEventListener("change", function (e) {
      if (e.target.type === "radio") { ss.ans[e.target.name] = e.target.value; save(); paint(); }
    });
    root.addEventListener("input", function (e) {
      if (e.target.dataset && e.target.dataset.note) { ss.notes[e.target.dataset.note] = e.target.value; save(); }
    });
    root.__rpReset = function () { ss.ans = {}; ss.notes = {}; restore(); paint(); };
    restore(); paint();
  }

  S.sections.forEach(function (sec) {
    var root = rootOf(sec);
    if (root) SETUP[sec.kind](sec, root, secState(st, sec));
  });

  /* ------------------------------------------------- page-level controls */
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
  var extra = one("[data-extra]");
  if (extra) {
    extra.value = st.extra || "";
    extra.addEventListener("input", function () { st.extra = extra.value; save(); });
  }
  var clear = one("#rp-clear");
  if (clear) clear.addEventListener("click", function () {
    if (!window.confirm("Clear every answer and note on this page?")) return;
    all("[data-section]").forEach(function (r) { if (r.__rpReset) r.__rpReset(); });
    save();
  });
  tally();
})();
