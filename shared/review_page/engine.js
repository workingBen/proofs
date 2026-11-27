/* Review page engine (proofs, shared/review_page). Built into every page by
   review_page.py; do not hand-edit a built page's copy.

   A page is a frame (S.mode: review, questions, log, session or settings: its chrome,
   tally and export header) around a list of sections (S.sections), each with a
   kind: review, questions, qa, log, settings, or the read-only links and decided. Each kind renders its own items, keeps its own state under
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

  /* ------------------------------------------------- settings: the checks settings.py makes
     The same rules as validate() in shared/settings.py, read from the table rows embedded
     in the page (min, max, raise_only, choices, item_type, path_kind, default) and the on/off words
     (S.bool_true, S.bool_false): no number is copied here, so the page refuses exactly what
     `settings.py --set` refuses, with the same reason. */
  function setCanon(v) {
    if (v === true || v === false) return v ? "1" : "0";
    if (Array.isArray(v)) return v.map(String).join(",");
    return String(v);
  }
  function setUnit(row) { return row.unit ? " " + row.unit : ""; }
  function SetRefused(msg) { this.message = msg; }
  function setInt(row, raw, what) {
    var text = String(raw).trim(), label = what || row.label;
    if (!/^[+-]?[0-9]+$/.test(text)) throw new SetRefused(label + " must be a whole number from " + row.min + " to " + row.max + ".");
    var n = parseInt(text, 10);
    if (row.raise_only && n < row["default"]) throw new SetRefused(row.label + " can only go up from " + row["default"] + setUnit(row) + ".");
    if (n < row.min || n > row.max) throw new SetRefused(label + " must be a whole number from " + row.min + " to " + row.max + setUnit(row) + ".");
    return n;
  }
  function setPath(row, text) {
    if (row.path_kind === "project") {
      if (/^[\/\\~]/.test(text) || /^[A-Za-z]:[\\\/]/.test(text)) throw new SetRefused(row.label + " must be a path inside the project, not an absolute one.");
      if (text.split(/[\\\/]/).indexOf("..") >= 0) throw new SetRefused(row.label + " cannot use .. to leave the project.");
    } else if (row.path_kind === "absolute" && text !== row["default"] && text.charAt(0) !== "/") {
      throw new SetRefused(row.label + " must be an absolute folder path (starting with /), or " + row["default"] + ".");
    }
    return text;
  }
  function setParse(S, row, raw) {
    if (raw !== null && raw !== undefined && /[\x00-\x1f\x7f]/.test(String(raw))) {
      throw new SetRefused(row.label + " cannot contain control characters such as a line break.");
    }
    var text = raw === null || raw === undefined ? "" : String(raw).trim();
    if (row.type === "int") return setInt(row, text);
    if (row.type === "choice") {
      if (row.choices.indexOf(text) < 0) throw new SetRefused(row.label + " must be one of: " + row.choices.join(", ") + ".");
      return row.choices.every(function (c) { return /^[0-9]+$/.test(c); }) ? parseInt(text, 10) : text;
    }
    if (row.type === "bool") {
      var low = text.toLowerCase();
      if ((S.bool_true || []).indexOf(low) >= 0) return true;
      if ((S.bool_false || []).indexOf(low) >= 0) return false;
      throw new SetRefused(row.label + " must be on or off (1 or 0).");
    }
    if (row.type === "list") {
      var items = text.split(",").map(function (p) { return p.trim(); }).filter(Boolean);
      if (row.item_type === "int") return items.map(function (i) { return setInt(row, i, row.label + " (each width)"); });
      if (!items.length && (row["default"] || []).length) throw new SetRefused(row.label + " needs at least one entry, separated by commas.");
      return items;
    }
    if (!text) throw new SetRefused(row.label + " cannot be empty.");
    return setPath(row, text);
  }
  // {ok, value, canon} for a value settings.py takes (canon is how it writes it), else {ok: false, error}.
  function settingCheck(S, row, raw) {
    try {
      var v = setParse(S, row, raw);
      return { ok: true, value: v, canon: setCanon(v) };
    } catch (e) {
      if (e instanceof SetRefused) return { ok: false, error: e.message };
      throw e;
    }
  }
  // What the reader has done to one setting: nothing, a refused value, the value it already
  // has, or a change (a valid value other than `from`, the value the page was built with).
  function setPending(S, row, ss) {
    var raw = ((ss || {}).ans || {})[row.id];
    if (raw === undefined || raw === null) return { state: "none" };
    var c = settingCheck(S, row, raw);
    if (!c.ok) return { state: "error", error: c.error };
    return c.canon === row.from ? { state: "same" } : { state: "change", value: c.value, canon: c.canon };
  }
  function setShown(row, v, unit) {
    var t;
    if (v === true || v === false) t = v ? "On" : "Off";
    else if (Array.isArray(v)) t = v.join(", ") || "none";
    else if (row.type === "choice") t = (row.choice_labels || {})[String(v)] || String(v);
    else t = String(v);
    if (unit === false || !row.unit || (Array.isArray(v) && !v.length)) return t;
    // "$ est." reads as "$5 est.", not "5 $ est."
    return row.unit.indexOf("$ ") === 0 ? "$" + t + " " + row.unit.slice(2) : t + " " + row.unit;
  }
  function setValueOf(S, row, canon) { return settingCheck(S, row, canon).value; }

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

  // A Refine item's changes are items marked with its id; after the last one, one line
  // names the changes answered Yes ("Combined: 1, 3"), or "Combined: none".
  function combinedLine(sec, refine, recs) {
    var yes = sec.items.filter(function (it) { return it.refine === refine && (recs[it.id] || {}).s === "accept"; })
      .map(function (it) { return it.num; });
    return "Combined: " + (yes.length ? yes.join(", ") : "none");
  }

  var BLOCK = {
    review: function (sec, ss) {
      var recs = ss.items || {}, lines = [];
      sec.items.forEach(function (it, i) {
        var l = reviewLine(sec, it, recs[it.id] || {});
        if (l !== null) lines.push(l);
        var next = sec.items[i + 1];
        if (it.refine && !(next && next.refine === it.refine)) lines.push(combinedLine(sec, it.refine, recs));
      });
      return lines;
    },
    questions: function (sec, ss) {
      var ans = ss.ans || {}, notes = ss.notes || {}, lines = [];
      sec.items.forEach(function (q) {
        lines.push("Q " + q.qid + " (raised r" + q.round + ") | " + q.ask);
        // A question with only a text box: what the reader typed is the answer.
        var typed = q.text && !ans[q.qid] ? noteLines("", notes[q.qid]) : [];
        if (typed.length) {
          lines.push("  -> " + typed[0]);
          typed.slice(1).forEach(function (l) { lines.push("     " + l); });
        } else {
          lines.push("  -> " + (ans[q.qid] || "(UNANSWERED)"));
          lines.push.apply(lines, noteLines("  note: ", notes[q.qid]));
        }
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
    // One line per change: SET KEY=VALUE (scope; was OLD), VALUE as settings.py --set takes it.
    settings: function (sec, ss, S) {
      var lines = [];
      sec.items.forEach(function (it) {
        var p = setPending(S, it, ss);
        if (p.state === "change") lines.push("SET " + it.id + "=" + p.canon + " (" + it.scope + "; was " + (it.from === "" ? "none" : it.from) + ")");
      });
      return lines;
    },
    links: function () { return []; },
    decided: function () { return []; }
  };

  function blocks(S, st) {
    var out = [];
    S.sections.forEach(function (sec) {
      out.push.apply(out, BLOCK[sec.kind](sec, ((st.sec || {})[sec.id]) || {}, S));
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
        var b = BLOCK[sec.kind](sec, ((st.sec || {})[sec.id]) || {}, S);
        if (!b.length) return;
        lines.push("");
        if (HEAD[sec.kind]) lines.push(HEAD[sec.kind], "");
        lines.push.apply(lines, b);
      });
      var extra = trimmed(st.extra);
      if (extra) lines.push("", "anything else:", extra);
      return lines.join("\n").replace(/\n{3,}/g, "\n\n").replace(/\n+$/, "") + "\n";
    },
    settings: function (S, st, now) {
      var lines = ["PROOFS SETTINGS — my changes", "project: " + S.project];
      if (S.repo) lines.push("repo: " + S.repo);
      lines.push("exported: " + localStamp(now), "");
      var b = blocks(S, st);
      return lines.concat(b.length ? b : ["(no changes)"]).join("\n") + "\n";
    }
  };

  // An item counts as answered when it has a pick, or, for a text-box-only question, typed text.
  function isAnswered(it, ss) {
    var id = it.qid || it.qaid;
    return !!((ss.ans || {})[id] || (it.text && trimmed((ss.notes || {})[id])));
  }

  function exportText(S, st, now) { return FRAME[S.mode](S, st || {}, now || new Date()); }

  /* ------------------------------------------------- answers in the page's database
     On a published claude.ai page with the db capability, each card's answer is one
     document in the "proofs-answers" collection, so Claude can read the answers with
     ArtifactData instead of waiting for a Copy and paste. These two functions turn page
     state into documents and back; both are pure, so node tests and answers.cjs share
     them with the page. */
  var DB_COLLECTION = "proofs-answers";
  function hash(s) {
    var h = 5381;
    for (var i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0;
    return h.toString(36);
  }
  // A document id is one path segment: letters, digits and _ - . ~ : @ + only.
  function docIdFor(secId, itemId) {
    var raw = secId + "." + itemId;
    var safe = raw.replace(/[^A-Za-z0-9_\-.~:@+]/g, "_").slice(0, 150);
    return safe === raw ? safe : safe + "~" + hash(raw);
  }
  function hasContent(b) {
    var a = b.answer;
    return !!((a && (typeof a !== "object" || Object.keys(a).length)) || b.note || b.read || b.variant || b.works_as_designed);
  }
  // { docId: body } for every card that holds anything. Bodies carry no timestamp.
  function answerDocs(S, st) {
    var out = {};
    function put(sec, id, kind, fields) {
      var b = { id: id, section: sec ? sec.id : "", kind: kind, answer: null, note: "", read: false };
      Object.keys(fields).forEach(function (k) { b[k] = fields[k]; });
      if (kind === "setting") delete b.read;
      if (hasContent(b)) out[sec ? docIdFor(sec.id, id) : "_page.extra"] = b;
    }
    S.sections.forEach(function (sec) {
      var ss = ((st.sec || {})[sec.id]) || {}, ans = ss.ans || {}, notes = ss.notes || {}, read = ss.read || {};
      sec.items.forEach(function (it) {
        if (sec.kind === "review") {
          var r = (ss.items || {})[it.id] || {};
          put(sec, it.id, "review", { answer: r.s || null, variant: r.v || null, works_as_designed: !!r.w,
                                     note: r.c || "", read: !!r.r });
        } else if (sec.kind === "questions" || sec.kind === "qa") {
          var id = it.qid || it.qaid;
          // A text-box-only question: what the reader typed is the answer.
          if (it.text && !ans[id]) put(sec, id, "question", { answer: notes[id] || null, note: "" });
          else put(sec, id, sec.kind === "qa" ? "qa" : "question", { answer: ans[id] || null, note: notes[id] || "" });
        } else if (sec.kind === "log") {
          var groups = {};
          (it.groups || []).forEach(function (g) { if (ans[it.id + "::" + g]) groups[g] = ans[it.id + "::" + g]; });
          put(sec, it.id, "log", { answer: groups, note: notes[it.id] || "", read: !!read[it.id] });
        } else if (sec.kind === "settings") {
          // A change only: a refused value, or the value it already has, is no answer.
          var p = setPending(S, it, ss);
          put(sec, it.id, "setting", { answer: p.state === "change" ? p.canon : null, from: it.from, scope: it.scope, note: "" });
        }
      });
    });
    if (st.extra) put(null, "extra", "extra", { note: st.extra });
    return out;
  }
  // Write documents (as answerDocs makes them, plus any metadata) back into page state.
  // Documents for cards no longer on the page are ignored. Mutates and returns st.
  function applyAnswerDocs(S, st, docs) {
    st.sec = st.sec || {};
    (docs || []).forEach(function (d) {
      if (!d || typeof d !== "object") return;
      if (d.kind === "extra") { st.extra = d.note || ""; return; }
      var sec = S.sections.filter(function (x) { return x.id === d.section; })[0];
      if (!sec) return;
      var it = sec.items.filter(function (i) { return (i.id || i.qid || i.qaid) === d.id; })[0];
      if (!it) return;
      var ss = secState(st, sec);
      if (sec.kind === "review") {
        ss.items = ss.items || {};
        var r = ss.items[d.id] = ss.items[d.id] || {};
        r.s = d.answer || null; r.v = d.variant || undefined; r.w = !!d.works_as_designed;
        r.c = d.note || ""; r.r = !!d.read;
      } else if (sec.kind === "questions" || sec.kind === "qa") {
        ss.ans = ss.ans || {}; ss.notes = ss.notes || {};
        if (it.text) {
          // Typed answers are stored as `answer`; rows from 1.6.8 carry them in `note`.
          delete ss.ans[d.id];
          ss.notes[d.id] = (typeof d.answer === "string" && d.answer) || d.note || "";
        } else {
          if (d.answer) ss.ans[d.id] = d.answer; else delete ss.ans[d.id];
          ss.notes[d.id] = d.note || "";
        }
      } else if (sec.kind === "log") {
        ss.ans = ss.ans || {}; ss.notes = ss.notes || {}; ss.read = ss.read || {};
        var a = d.answer && typeof d.answer === "object" ? d.answer : {};
        (it.groups || []).forEach(function (g) {
          if (a[g]) ss.ans[d.id + "::" + g] = a[g]; else delete ss.ans[d.id + "::" + g];
        });
        ss.notes[d.id] = d.note || "";
        ss.read[d.id] = !!d.read;
      } else if (sec.kind === "settings") {
        ss.ans = ss.ans || {};
        if (typeof d.answer === "string") ss.ans[d.id] = d.answer; else delete ss.ans[d.id];
      }
    });
    return st;
  }
  // Key-order-independent JSON, to compare a stored body with the page's.
  function canon(v) {
    if (v === null || typeof v !== "object") return JSON.stringify(v === undefined ? null : v);
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    return "{" + Object.keys(v).sort().map(function (k) { return JSON.stringify(k) + ":" + canon(v[k]); }).join(",") + "}";
  }
  var META = ["updated_at", "page_version", "page"];
  function bodyOf(d) {
    var b = {};
    Object.keys(d || {}).forEach(function (k) { if (META.indexOf(k) < 0) b[k] = d[k]; });
    return b;
  }

  /* ------------------------------------------------- Send to Claude, the pure parts
     A db write starts no turn, so the session that published the page waits for a paste.
     Send to Claude posts a comment with the comments capability's sendToClaude, which
     wakes that session. The text is a short pointer to the saved rows, not the export:
     sendToClaude refuses more than 4 KiB, and the database holds everything. */
  var SEND_MAX_BYTES = 4000, SEND_STALE_DEFAULT_MS = 5 * 60 * 1000, SEND_FORGET_MS = 24 * 60 * 60 * 1000;
  var SENT_MSG = "Sent. This page updates when Claude has read your answers (usually under a minute). " +
                 "The reply is also in the comments.";
  function cpBytes(c) { return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; }
  // At most max bytes of UTF-8, cut on a whole character, with "…" when cut.
  function clipBytes(s, max) {
    var n = 0, out = "", chars = Array.from(s);
    for (var i = 0; i < chars.length; i++) {
      var b = cpBytes(chars[i].codePointAt(0));
      if (n + b > max - 3) {
        var rest = chars.slice(i).reduce(function (t, ch) { return t + cpBytes(ch.codePointAt(0)); }, 0);
        return n + rest <= max ? s : out + "…";
      }
      n += b; out += chars[i];
    }
    return out;
  }
  // sendToClaude refuses control characters other than newlines and tabs.
  function plainText(s) { return String(s || "").replace(/\r\n?/g, "\n").replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, ""); }
  var ANSWER_KINDS = ["review", "questions", "qa", "log", "settings"];
  // The ids of every card that holds an answer (the "Anything else" box is not a card).
  function answeredIds(S, st) {
    var docs = answerDocs(S, st || {}), ids = [];
    Object.keys(docs).forEach(function (k) { if (docs[k].kind !== "extra") ids.push(docs[k].id); });
    return ids;
  }
  function answeredCount(S, st) { return answeredIds(S, st).length; }
  function sendText(S, st) {
    st = st || {};
    var total = 0;
    S.sections.forEach(function (sec) { if (ANSWER_KINDS.indexOf(sec.kind) >= 0) total += sec.items.length; });
    var ids = answeredIds(S, st);
    var name = S.session || S.stream || S.project || "Proofs";
    var ver = S.version || S.page_version;
    var what = ids.length ? "answered " + clipBytes(ids.join(", "), 1500) : "nothing answered yet";
    var text = plainText(name + " page " + ver + ": " + what + " (" + ids.length + " of " + total + ")." +
                         " Read proofs-answers on this artifact.");
    var extra = trimmed(plainText(st.extra));
    if (extra) text += "\n\nAnything else: " + extra;
    return clipBytes(text, SEND_MAX_BYTES);
  }
  function clock(d) {
    try { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
    catch (e) { return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  }
  // What the bar says on load after a send ({sentAt, fromVersion} kept in localStorage).
  // The page cannot read the comment thread, so a newer version of the page is the proof
  // that Claude read the answers: Claude's first act on a send is to republish.
  // The wait comes from the page's own spec (send_wait_ms, built from the PROOFS_SEND_WAIT_MIN setting).
  function staleMs(S) { return (S && S.send_wait_ms) || SEND_STALE_DEFAULT_MS; }
  function pickupNote(sent, S, now) {
    var SEND_STALE_MS = staleMs(S);
    if (!sent || !sent.sentAt) return null;
    var at = new Date(sent.sentAt), age = (+now) - at.getTime();
    if (isNaN(age)) return null;
    if (sent.fromVersion !== S.page_version) {
      return { tone: "ok", clear: true,
               text: "Claude picked up your answers (sent " + clock(at) + (S.version ? ", now " + S.version : "") + ")" };
    }
    if (age > SEND_FORGET_MS) return { tone: "", text: "", clear: true };
    if (age > SEND_STALE_MS) {
      return { tone: "warn", clear: false, text: "Not picked up yet. The session may be busy or closed; Copy still works." };
    }
    return { tone: "ok", clear: false, text: SENT_MSG, wait: SEND_STALE_MS - age };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { exportText: exportText, answeredCount: answeredCount, answerDocs: answerDocs, applyAnswerDocs: applyAnswerDocs,
                       docIdFor: docIdFor, DB_COLLECTION: DB_COLLECTION, sendText: sendText, pickupNote: pickupNote,
                       settingCheck: settingCheck };
  }
  if (typeof document === "undefined") return;

  /* ------------------------------------------------- the page */
  var S = JSON.parse(document.getElementById("rp-spec").textContent);
  var st = {};
  try { st = JSON.parse(localStorage.getItem(S.key) || "{}") || {}; } catch (e) { st = {}; }
  function store() { try { localStorage.setItem(S.key, JSON.stringify(st)); } catch (e) { /* private window */ } }
  // Which cards changed since the last save, stamped in st.at (when) and st.unsent (not
  // yet in the store), so a change the page never got to send survives a reload and is
  // pushed then. Typing waits for a pause (save()); a tap is sent at once (saveNow()).
  var lastDocs = answerDocs(S, st);
  function noteEdits() {
    var cur = answerDocs(S, st), now = new Date().toISOString();
    Object.keys(cur).concat(Object.keys(lastDocs)).forEach(function (id) {
      if (canon(cur[id] || null) === canon(lastDocs[id] || null)) return;
      st.at = st.at || {}; st.at[id] = now;
      st.unsent = st.unsent || {}; st.unsent[id] = now;
    });
    lastDocs = cur;
  }
  function save() { noteEdits(); store(); dbSchedule(); sendCheck(); }
  function saveNow() { noteEdits(); store(); dbFlushNow(); sendCheck(); }
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
      var ss = secState(st, sec);
      sec.items.forEach(function (it) { total++; if (isAnswered(it, ss)) done++; });
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
  TALLY.settings = function () {
    var sec = ofKind("settings")[0];
    if (!sec) return;
    var ss = secState(st, sec), changes = [], per = {};
    sec.items.forEach(function (it) {
      var p = setPending(S, it, ss), g = per[it.group] = per[it.group] || { pending: 0, changed: 0 };
      if (p.state === "change") {
        g.pending++;
        changes.push(it.label + " " + setShown(it, setValueOf(S, it, it.from), false) + " → " + setShown(it, p.value));
      } else if (it.from !== setCanon(it["default"])) g.changed++;
    });
    var n = changes.length;
    one("[data-set-count]").textContent = n ? n + (n === 1 ? " change" : " changes") + " not saved yet" : "No changes yet";
    var list = one("[data-set-list]");
    if (!list.dataset.none) list.dataset.none = list.textContent;
    list.textContent = n ? changes.join(" · ") : list.dataset.none;
    all("[data-set-nav]").forEach(function (a) {
      var g = per[a.dataset.setNav] || { pending: 0, changed: 0 }, dot = one("[data-set-dot]", a);
      a.classList.toggle("rp-set-has-dot", !!(g.pending || g.changed));
      dot.classList.toggle("rp-set-dot-p", !!g.pending);
      if (g.pending) dot.setAttribute("aria-label", g.pending + " not saved");
      else if (g.changed) dot.setAttribute("aria-label", g.changed + " changed");
      else dot.removeAttribute("aria-label");
      dot.setAttribute("role", g.pending || g.changed ? "img" : "presentation");
    });
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
      function paint() { all(".rp-item", root).forEach(paintItem); tally(); refineSync(); }
      root.__rpRefresh = paint;
      all(".rp-item", root).forEach(function (card) {
        var id = card.dataset.id;
        all(".rp-btn", card).forEach(function (b) {
          b.addEventListener("click", function () {
            var r = rec(id);
            r.s = r.s === b.dataset.choice ? null : b.dataset.choice;
            saveNow(); paint();
            var bt = r.s ? buttonFor(sec, r.s) : null;
            if (bt && bt.comment === "required") one("textarea", card).focus();
          });
        });
        all(".rp-variant", card).forEach(function (el) {
          function pick() { rec(id).v = el.dataset.variant; saveNow(); paint(); }
          el.addEventListener("click", function (e) { if (!e.target.closest("a,input,textarea,select")) pick(); });
          el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        });
        one("textarea", card).addEventListener("input", function (e) { rec(id).c = e.target.value; save(); tally(); });
        var wad = one("[data-wad]", card);
        if (wad) wad.addEventListener("change", function () { rec(id).w = wad.checked; saveNow(); });
        var read = one("[data-read]", card);
        if (read) read.addEventListener("change", function () { rec(id).r = read.checked; saveNow(); paint(); });
      });
      all(".rp-item", root).forEach(paintItem);
    },
    questions: answerable,
    qa: answerable,
    settings: settingsSetup,
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
      function restore() {
        all("input[type=radio]", root).forEach(function (r) { r.checked = ss.ans[r.name] === r.value; });
        all("[data-note]", root).forEach(function (t) { t.value = ss.notes[t.dataset.note] || ""; });
        all("[data-tick]", root).forEach(function (t) { t.checked = !!ss.read[t.dataset.tick]; });
      }
      restore();
      root.__rpRefresh = function () { restore(); paint(); };
      root.addEventListener("change", function (e) {
        var t = e.target;
        if (t.type === "radio") { ss.ans[t.name] = t.value; saveNow(); paint(); return; }
        if (!(t.dataset && t.dataset.tick)) return;
        var card = t.closest("[data-entry]");
        var wasTop = card ? card.getBoundingClientRect().top : 0, wasY = window.scrollY;
        ss.read[t.dataset.tick] = t.checked;
        saveNow(); paint();
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
    var byId = {};
    sec.items.forEach(function (it) { byId[it.qid || it.qaid] = it; });
    function paint() {
      all(".q", root).forEach(function (c) { c.classList.toggle("answered", isAnswered(byId[c.dataset.qid] || {}, ss)); });
      all(".qa", root).forEach(function (c) {
        var v = ss.ans[c.dataset.qaid];
        c.classList.toggle("pass", v === "PASS");
        c.classList.toggle("fail", v === "FAIL");
        c.classList.toggle("skip", v === "COULDN'T TEST");
      });
      tally();
    }
    root.addEventListener("change", function (e) {
      if (e.target.type === "radio") { ss.ans[e.target.name] = e.target.value; saveNow(); paint(); }
    });
    root.addEventListener("input", function (e) {
      var id = e.target.dataset && e.target.dataset.note;
      if (!id) return;
      ss.notes[id] = e.target.value; save();
      if ((byId[id] || {}).text) paint();
    });
    root.__rpReset = function () { ss.ans = {}; ss.notes = {}; restore(); paint(); };
    root.__rpRefresh = function () { restore(); paint(); };
    restore(); paint();
  }

  // The settings page: one row per setting, one group's pane at a time, a search across all.
  function settingsSetup(sec, root, ss) {
    ss.ans = ss.ans || {};
    var byKey = {}, opened = {}, groups = sec.groups || [];
    sec.items.forEach(function (it) { byKey[it.id] = it; });
    var search = one("[data-set-search]", root), none = one("[data-set-none]", root);
    function rowEl(k) { return one('[data-set-row="' + k + '"]', root); }
    function boxText(it) { return Array.isArray(it.value) ? it.value.join(", ") : setCanon(it.value); }
    function current(it) {
      var p = setPending(S, it, ss);
      return p.state === "change" ? p.value : setValueOf(S, it, it.from);
    }
    function link(text, attr) {
      var b = document.createElement("button");
      b.type = "button"; b.className = "rp-set-link"; b.setAttribute(attr, ""); b.textContent = text;
      return b;
    }
    function paintRow(k) {
      var it = byKey[k], el = rowEl(k), p = setPending(S, it, ss);
      el.classList.toggle("rp-set-row-p", p.state === "change");
      el.classList.toggle("rp-set-row-bad", p.state === "error");
      var err = one("[data-set-err]", el);
      err.hidden = p.state !== "error";
      err.textContent = p.state === "error" ? p.error : "";
      var box = one("[data-set-in]", el);
      if (box) { if (p.state === "error") box.setAttribute("aria-invalid", "true"); else box.removeAttribute("aria-invalid"); }
      var mark = one("[data-set-mark]", el);
      mark.textContent = "";
      mark.className = "rp-set-mark" + (p.state === "change" ? " rp-set-mark-p" : "");
      if (p.state === "change") {
        mark.appendChild(document.createTextNode("Not saved · was " + setShown(it, setValueOf(S, it, it.from)) + " · "));
        mark.appendChild(link("Undo", "data-set-undo"));
      } else if (it.from !== setCanon(it["default"])) {
        mark.appendChild(document.createTextNode("Changed · default " + setShown(it, it["default"]) + " · "));
        mark.appendChild(link("Reset", "data-set-reset"));
      }
      mark.hidden = !mark.childNodes.length;
      var v = current(it);
      all("[data-set-choice]", el).forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.setChoice === setCanon(v))); });
      var tog = one("[data-set-tog]", el);
      if (tog) { tog.setAttribute("aria-checked", String(v === true)); one("[data-set-tog-l]", tog).textContent = v ? "On" : "Off"; }
      var auto = one("[data-set-auto]", el);
      if (auto) {
        var typed = opened[k] || ss.ans[k] !== undefined || it.from !== "auto";
        auto.hidden = typed;
        box.hidden = !typed;
      }
    }
    function syncBox(k) {
      var box = one("[data-set-in]", rowEl(k)), it = byKey[k];
      if (!box) return;
      var want = ss.ans[k] !== undefined ? String(ss.ans[k]) : boxText(it);
      if (box.value !== want) box.value = want;
    }
    function hay(it) {
      var labels = it.choice_labels ? Object.keys(it.choice_labels).map(function (c) { return it.choice_labels[c]; }) : [];
      return [it.id, it.label, it.help].concat(labels).join(" ").toLowerCase();
    }
    function activeGroup() {
      return groups.some(function (g) { return g[0] === ss.group; }) ? ss.group : (groups[0] || [""])[0];
    }
    function paintGroups() {
      var q = trimmed(search ? search.value : "").toLowerCase(), active = activeGroup(), any = false;
      groups.forEach(function (g) {
        var pane = one('[data-set-group="' + g[0] + '"]', root), shown = 0, adv = 0, total = 0;
        all("[data-set-row]", pane).forEach(function (el) {
          var it = byKey[el.dataset.setRow], hit = !q || hay(it).indexOf(q) >= 0;
          total++;
          el.hidden = !hit;
          if (hit) { shown++; if (it.advanced) adv++; }
        });
        var h = one("[data-set-adv-h]", pane);
        if (h) h.hidden = !adv;
        pane.hidden = q ? !shown : g[0] !== active;
        any = any || !!shown;
        var a = one('[data-set-nav="' + g[0] + '"]', root), on = !q && g[0] === active;
        a.classList.toggle("rp-set-nav-on", on);
        a.classList.toggle("rp-set-nav-empty", !!q && !shown);
        if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
        // The count is what tapping the group shows: its matches while searching.
        one("[data-set-n]", a).textContent = q ? shown : total;
      });
      if (none) none.hidden = !q || any;
    }
    function set(k, raw) {
      if (raw === byKey[k].from) delete ss.ans[k]; else ss.ans[k] = raw;
      syncBox(k); saveNow(); paintRow(k); tally();
    }
    function refocus(k) {
      var c = one("[data-set-in]:not([hidden]), [data-set-choice][aria-pressed=true], [data-set-tog], [data-set-change]", rowEl(k));
      if (c) c.focus();
    }
    root.addEventListener("click", function (e) {
      var nav = e.target.closest("[data-set-nav]");
      if (nav) {
        e.preventDefault();
        if (trimmed(search.value)) {
          var pane = one('[data-set-group="' + nav.dataset.setNav + '"]', root);
          if (pane && !pane.hidden) pane.scrollIntoView({ block: "start" });
          return;
        }
        ss.group = nav.dataset.setNav; store(); paintGroups();
        return;
      }
      var el = e.target.closest("[data-set-row]");
      if (!el) return;
      var k = el.dataset.setRow, it = byKey[k], b = e.target.closest("[data-set-choice]");
      if (b) set(k, b.dataset.setChoice);
      else if (e.target.closest("[data-set-tog]")) set(k, current(it) ? "0" : "1");
      else if (e.target.closest("[data-set-reset]")) { set(k, setCanon(it["default"])); refocus(k); }
      else if (e.target.closest("[data-set-undo]")) { delete ss.ans[k]; syncBox(k); saveNow(); paintRow(k); tally(); refocus(k); }
      else if (e.target.closest("[data-set-change]")) { opened[k] = true; paintRow(k); one("[data-set-in]", el).focus(); }
    });
    root.addEventListener("input", function (e) {
      if (e.target === search) { paintGroups(); return; }
      var k = e.target.dataset && e.target.dataset.setIn;
      if (!k) return;
      ss.ans[k] = e.target.value;
      save(); paintRow(k); tally();
    });
    function restore() { sec.items.forEach(function (it) { syncBox(it.id); paintRow(it.id); }); }
    root.__rpRefresh = function () { restore(); paintGroups(); tally(); };
    restore(); paintGroups(); tally();
  }

  S.sections.forEach(function (sec) {
    var root = rootOf(sec);
    if (root) SETUP[sec.kind](sec, root, secState(st, sec));
  });

  /* ------------------------------------------------- the Refine preview (design-review)
     Both frames get the page's one embedded snapshot as their srcdoc. A srcdoc load
     replaces the frame's document, so a frame is painted only after its load event, and
     again after any later load. Painting writes the Yes set (or nothing, in the Original
     view) to the frame's <html data-rc>, and puts each on change's swaps in place. */
  var rc = null;
  function refineSync() { if (rc) rc.sync(); }
  (function () {
    var preview = one("[data-rc-preview]");
    var baseEl = preview && document.getElementById("rp-rc-base-" + preview.dataset.rcPreview);
    if (!baseEl) return;
    var refine = preview.dataset.rcPreview;
    var sec = S.sections.filter(function (s) {
      return s.kind === "review" && s.items.some(function (i) { return i.refine === refine; });
    })[0];
    if (!sec) return;
    var ids = sec.items.filter(function (i) { return i.refine === refine; }).map(function (i) { return i.id; });
    var view = "picks";
    // Set only through rpRefine.only, for measuring: the on set whatever the answers say.
    var only = null;
    var frames = all(".rp-rc-frame", preview);
    function picks() {
      var recs = secState(st, sec).items || {};
      return ids.filter(function (id) { return (recs[id] || {}).s === "accept"; });
    }
    // Every swap in place is undone (last first), then the on changes' swaps are made in
    // spec order, so two swaps on one element always come back to the original.
    function swaps(f, d, on) {
      var done = f.__rcSwaps || [];
      for (var i = done.length - 1; i >= 0; i--) {
        var s = done[i];
        if (s.now[0] && s.now[0].parentNode) {
          s.now[0].parentNode.insertBefore(s.orig, s.now[0]);
          s.now.forEach(function (n) { if (n.parentNode) n.parentNode.removeChild(n); });
        }
      }
      f.__rcSwaps = [];
      all("template[data-rc-swap]", d).forEach(function (tpl) {
        if (on.indexOf(tpl.dataset.rcSwap) < 0) return;
        var targets;
        try { targets = all(tpl.dataset.rcTarget, d); } catch (e) { return; }
        targets.forEach(function (el) {
          var frag = tpl.content.cloneNode(true), now = Array.prototype.slice.call(frag.childNodes);
          if (!now.length) return;
          el.parentNode.insertBefore(frag, el);
          el.parentNode.removeChild(el);
          f.__rcSwaps.push({ orig: el, now: now });
        });
      });
    }
    // Scale = the column's width / the frame's width (never above 1); the box takes the
    // scaled size, so the page never scrolls sideways.
    function fit(f) {
      var d = f.__rcDoc, box = f.parentNode, fig = box.parentNode;
      var w = +f.dataset.rcWidth, edge = box.offsetWidth - box.clientWidth;
      var s = Math.min(1, Math.max(0, fig.clientWidth - edge) / w);
      // The page's own height, not scrollHeight: that never drops below the frame's
      // current height, so a frame would grow with a change and never shrink back.
      var h = d && d.documentElement ? Math.ceil(d.documentElement.getBoundingClientRect().height) : 0;
      f.style.height = h + "px";
      f.style.transform = s < 1 ? "scale(" + s + ")" : "";
      box.style.width = Math.floor(w * s) + "px";
      box.style.height = Math.ceil(h * s) + "px";
    }
    function paint(f) {
      var d = f.__rcDoc;
      if (!d || f.contentDocument !== d) return;
      var on = only || (view === "picks" ? picks() : []);
      d.documentElement.setAttribute("data-rc", on.join(" "));
      swaps(f, d, on);
      fit(f);
      f.dataset.rcReady = "1";
    }
    function sync() {
      all("[data-rc-view]", preview).forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.rcView === view)); });
      frames.forEach(paint);
    }
    rc = { sync: sync };
    frames.forEach(function (f) {
      f.addEventListener("load", function () {
        var d = f.contentDocument;
        // Only the snapshot counts: WebKit can fire a load for the frame's initial
        // about:blank after this listener is attached, and painting that would mark the
        // frame ready before the snapshot is in it.
        if (!d || !d.querySelector("style[data-rc-css]")) { f.__rcDoc = null; delete f.dataset.rcReady; return; }
        f.__rcDoc = d;
        f.__rcSwaps = [];
        paint(f);
        // Sizes change without a window resize: the page's scrollbar appearing, web fonts
        // or images arriving late, content that grows. Watch the frame's page too.
        var RO = d.defaultView && d.defaultView.ResizeObserver;
        if (RO) new RO(function () { if (f.__rcDoc === d) fit(f); }).observe(d.documentElement);
      });
    });
    if (window.ResizeObserver) {
      var figRO = new ResizeObserver(function (es) {
        es.forEach(function (e) {
          var f = one(".rp-rc-frame", e.target);
          if (f && f.__rcDoc) fit(f);
        });
      });
      frames.forEach(function (f) { figRO.observe(f.parentNode.parentNode); });
    }
    all("[data-rc-view]", preview).forEach(function (b) {
      b.addEventListener("click", function () { view = b.dataset.rcView; sync(); });
    });
    // A fallback for browsers without ResizeObserver.
    var fitAll = function () { frames.forEach(function (f) { if (f.__rcDoc) fit(f); }); };
    window.addEventListener("resize", fitAll);
    // only(ids) is for --smoke, not readers: both frames show exactly these changes, whatever
    // the answers say and without touching them; only(null) goes back to the answers. state()
    // still reports the answers.
    window.rpRefine = {
      state: function () { return { on: picks(), view: view }; },
      only: function (on) { only = on ? on.slice() : null; sync(); },
    };
    var base = JSON.parse(baseEl.textContent);
    frames.forEach(function (f) { f.srcdoc = base; });
    sync();
  })();

  /* ------------------------------------------------- the page's database, when present
     Without the runtime (a local file, an older contract, a signed-out viewer) none of
     this runs and the page works from localStorage alone, as before. Copy never waits
     on it. */
  var DB_DEBOUNCE_MS = 800, DB_LOAD_TIMEOUT_MS = 10000, DB_RETRY_MAX_MS = 30000;
  // base: each document as last written (or read); chain: one write at a time per
  // document; inflight: writes not yet settled, per document; failed: documents whose
  // last write failed and wait for a retry; stale: documents left unsent by an earlier
  // visit, shown as "Not saved yet" until they land.
  var dbs = { db: null, base: {}, timer: null, chain: {}, inflight: {}, failed: {}, stale: {}, off: false,
              tries: 0, retry: null };
  function dbState(v) { document.body.setAttribute("data-answers-db", v); }
  function dbSchedule() {
    if (!dbs.db || dbs.off) return;
    clearTimeout(dbs.timer);
    dbs.timer = setTimeout(function () { dbs.timer = null; dbFlush(); }, DB_DEBOUNCE_MS);
    syncPaint();
  }
  // Taps, blur, leaving the page: write now, not after the debounce.
  function dbFlushNow() {
    if (!dbs.db || dbs.off) return;
    clearTimeout(dbs.timer);
    dbs.timer = null;
    dbFlush();
  }
  function cleared(b) {
    // An undone setting keeps the row's shape (answer null means no change to apply).
    if (b.kind === "setting") return { id: b.id, section: b.section, kind: b.kind, answer: null, from: b.from, scope: b.scope, note: "" };
    return { id: b.id, section: b.section, kind: b.kind, answer: b.kind === "log" ? {} : null, note: "", read: false,
             variant: b.kind === "review" ? null : undefined, works_as_designed: b.kind === "review" ? false : undefined };
  }
  function dbFlush() {
    if (!dbs.db || dbs.off) return;
    var cur = answerDocs(S, st), unsent = st.unsent || {};
    var ids = {};
    Object.keys(cur).concat(Object.keys(dbs.base), Object.keys(dbs.failed), Object.keys(unsent))
      .forEach(function (id) { ids[id] = 1; });
    Object.keys(ids).forEach(function (id) {
      var body = cur[id] || (dbs.base[id] ? cleared(dbs.base[id]) : null);
      var same = !body || (dbs.base[id] && canon(bodyOf(body)) === canon(dbs.base[id]));
      if (same && !dbs.failed[id]) {
        // Nothing to send: an unsent mark whose content the store already holds is done.
        if (unsent[id] && !dbs.inflight[id]) { delete unsent[id]; delete dbs.stale[id]; store(); }
        return;
      }
      if (body) dbWrite(id, JSON.parse(JSON.stringify(body)));
    });
    syncPaint();
  }
  function dbRetryLater() {
    if (dbs.retry || dbs.off) return;
    var wait = Math.min(DB_RETRY_MAX_MS, 1000 * Math.pow(2, dbs.tries)) + Math.random() * 300;
    dbs.tries++;
    dbs.retry = setTimeout(function () { dbs.retry = null; dbFlush(); }, wait);
  }
  // A failure that retrying will not fix: not allowed to write here, or the store is gone.
  var DB_RETRYABLE = ["unavailable", "resource_exhausted", "deadline_exceeded", "aborted", "internal", "unknown"];
  function dbWrite(id, body) {
    var now = new Date().toISOString();
    var full = bodyOf(body);
    full.updated_at = now; full.page_version = S.page_version || null; full.page = S.key;
    dbs.base[id] = bodyOf(body);
    delete dbs.failed[id];
    st.at = st.at || {}; st.at[id] = now; store();
    var edit = (st.unsent || {})[id];
    dbs.inflight[id] = (dbs.inflight[id] || 0) + 1;
    dbs.chain[id] = (dbs.chain[id] || Promise.resolve()).then(function () {
      return dbs.db.collection(DB_COLLECTION).doc(id).set(full);
    }).then(function () {
      dbs.inflight[id]--;
      delete dbs.stale[id];
      // Done, unless the reader changed the card again while this write was out.
      if (st.unsent && st.unsent[id] === edit) { delete st.unsent[id]; store(); }
      if (!Object.keys(dbs.failed).length) dbs.tries = 0;
      dbState("on");
      syncPaint();
    }, function (e) {
      dbs.inflight[id]--;
      dbs.failed[id] = true;
      var code = e && e.code;
      if (code && DB_RETRYABLE.indexOf(code) < 0) {
        dbs.off = true;  // stay on localStorage and Copy
        clearTimeout(dbs.retry);
        dbState("off");
      } else {
        dbState("error");
        dbRetryLater();
      }
      syncPaint();
    });
  }

  /* The header's sync indicator: Saved, Saving… or Not saved yet. Shown only once the
     page's database has answered, so a page that cannot save never claims "Saved". */
  var SYNC = {
    saved: ["Saved", "Every answer is stored with this page",
            '<path d="M3.5 8.5l3 3 6-7"/>'],
    saving: ["Saving…", "Storing your latest change",
             '<circle cx="8" cy="8" r="5.5" stroke-dasharray="3 2.2"/>'],
    // " yet" drops on a phone, where the bar is one line (it is still read out)
    unsaved: ['Not saved<span class="rp-sync-x"> yet</span>', "Not stored yet; it keeps trying. Copy still sends everything",
              '<circle cx="8" cy="8" r="6"/><path d="M8 4.6v4.2"/><path d="M8 11.2v.2"/>']
  };
  function syncState() {
    var unsent = Object.keys(st.unsent || {}).length;
    if (dbs.off) return unsent || Object.keys(dbs.failed).length ? "unsaved" : null;
    if (!dbs.db) return null;
    if (Object.keys(dbs.failed).length || Object.keys(dbs.stale).length) return "unsaved";
    var busy = dbs.timer || Object.keys(dbs.inflight).some(function (id) { return dbs.inflight[id] > 0; });
    return busy || unsent ? "saving" : "saved";
  }
  function syncPaint() {
    var el = one("[data-sync]");
    if (!el) return;
    var s = syncState();
    if (el.getAttribute("data-state") === (s || "")) return;
    el.setAttribute("data-state", s || "");
    document.body.setAttribute("data-rp-sync", s || "none");
    el.hidden = !s;
    if (!s) return;
    var d = SYNC[s];
    el.title = d[1];
    one("svg", el).innerHTML = d[2];
    one(".rp-sync-t", el).innerHTML = d[0];
  }

  function refreshAll() {
    all("[data-section]").forEach(function (r) { if (r.__rpRefresh) r.__rpRefresh(); });
    var ex = one("[data-extra]");
    if (ex) ex.value = st.extra || "";
    tally();
  }
  function dbLoad(db) {
    var done = false;
    var timer = setTimeout(function () { done = true; dbState("unreachable"); }, DB_LOAD_TIMEOUT_MS);
    db.collection(DB_COLLECTION).get().then(function (snap) {
      if (done) return;
      clearTimeout(timer);
      dbs.db = db;
      var at = st.at || {}, remote = [], unsent = st.unsent || {};
      (snap.docs || []).forEach(function (d) {
        if (!d.exists) return;
        var body = d.data() || {};
        // Only cards still on this page take part, so a republish never clears old rows.
        var sec = S.sections.filter(function (x) { return x.id === body.section; })[0];
        if (body.kind !== "extra" && !(sec && sec.items.some(function (i) { return (i.id || i.qid || i.qaid) === body.id; }))) return;
        dbs.base[d.id] = bodyOf(body);
        // The newer updated_at wins: a local change the store never got is pushed below.
        if (!(at[d.id] && at[d.id] > (body.updated_at || ""))) {
          remote.push(body);
          st.at = st.at || {}; st.at[d.id] = body.updated_at || "";
          delete unsent[d.id];
        }
      });
      // What is left was changed here and never reached the store: say so until it lands.
      Object.keys(unsent).forEach(function (id) { dbs.stale[id] = true; });
      applyAnswerDocs(S, st, remote);
      lastDocs = answerDocs(S, st);
      store();
      refreshAll();
      sendCheck();
      dbState("on");
      dbFlush();
    }, function () { clearTimeout(timer); dbState("off"); });
  }
  function dbConnect() {
    var c = window.claude;
    if (!c || typeof c.use !== "function") return false;
    Promise.resolve().then(function () { return c.use("db"); }).then(function (db) {
      if (db) dbLoad(db); else dbState("off");
    }, function () { dbState("off"); });
    return true;
  }
  if (!dbConnect()) window.addEventListener("load", dbConnect, { once: true });
  // Leaving the page, switching apps or leaving a text box sends what is pending at once.
  window.addEventListener("pagehide", dbFlushNow);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden" || Object.keys(dbs.failed).length) dbFlushNow();
  });
  document.addEventListener("focusout", function (e) {
    if (e.target && /^(TEXTAREA|INPUT)$/.test(e.target.tagName) && dbs.timer) dbFlushNow();
  });
  window.addEventListener("online", function () { if (Object.keys(dbs.failed).length) dbFlushNow(); });

  /* ------------------------------------------------- Send to Claude, on the page
     Shown only once window.claude.use("comments") answers; enabled only while
     canSendToClaude() says "available", re-checked whenever the page is shown again. A
     tap saves first (waits for Saved), then sends. "Sent" shows only after sendToClaude
     resolves, and nothing ever retries by itself. */
  var SEND_WAIT_MS = 5000, SEND_KEY = S.key + ":sent";
  var SEND_WHY = { no_session: "This page's Claude session isn't listening; use Copy",
                   writers_only: "Only editors can send; use Copy", off: "Not available here; use Copy",
                   none: "Answer something first: Send sends your saved answers." };
  var SEND_ERR = {
    consent_required: "Not sent. Allow commenting when asked, then tap again.",
    claude_unavailable: "Nothing was sent; use Copy.",
    rate_limited: "Not sent: too many sends just now. Wait a minute, then tap again.",
    not_saved: "Nothing was sent: your answers are not saved on the page yet. Use Copy."
  };
  var SEND_FINAL = ["forbidden", "not_granted", "capability_disabled", "capability_removed"];
  var sendBtn = one("[data-send]"), sendMsg = one("[data-send-msg]");
  var snd = { comments: null, busy: false, held: false, staleTimer: null };
  function sendSay(text, tone) {
    if (!sendMsg) return;
    sendMsg.textContent = text || "";
    sendMsg.hidden = !text;
    sendMsg.setAttribute("data-tone", tone || "");
  }
  // Nothing to send until a card holds an answer or the "Anything else" box holds text.
  function sendNothing() { return !answeredCount(S, st) && !trimmed(plainText(st.extra)); }
  function sendCheck() {
    if (!snd || !snd.comments || !sendBtn || snd.busy || snd.held) return;
    Promise.resolve().then(function () { return snd.comments.canSendToClaude(); })
      .then(null, function () { return "off"; })
      .then(function (can) {
        if (snd.busy || snd.held) return;
        sendBtn.hidden = false;
        var why = can !== "available" ? (SEND_WHY[can] || SEND_WHY.off) : sendNothing() ? SEND_WHY.none : "";
        sendBtn.disabled = !!why;
        var tone = sendMsg ? sendMsg.getAttribute("data-tone") || "" : "";
        // A reason replaces only a reason (or nothing): it never hides what a send said.
        if (!why) { if (tone === "why") sendSay(""); }
        else if (!tone || tone === "why") sendSay(why, "why");
      });
  }
  function waitSaved(ms) {
    var t0 = Date.now();
    return new Promise(function (res) {
      (function poll() {
        var s = syncState();
        if (s === "saved") return res(true);
        if (!s || dbs.off || Date.now() - t0 > ms) return res(false);
        setTimeout(poll, 100);
      })();
    });
  }
  function watchStale(wait) {
    clearTimeout(snd.staleTimer);
    snd.staleTimer = setTimeout(function () {
      var n = pickupNote(readSent(), S, Date.now());
      if (n && n.tone === "warn") sendSay(n.text, n.tone);
    }, Math.max(0, wait) + 50);
  }
  function readSent() {
    try { return JSON.parse(localStorage.getItem(SEND_KEY) || "null"); } catch (e) { return null; }
  }
  if (sendBtn) sendBtn.addEventListener("click", function () {
    if (snd.busy || !snd.comments) return;
    snd.busy = true;
    sendBtn.disabled = true;
    sendSay("Saving your answers first…", "busy");
    // The anchor is taken at the tap; the send waits for the saves to land.
    var anchor = Promise.resolve().then(function () { return snd.comments.anchorFor(sendBtn); });
    anchor.then(null, function () {});
    saveNow();
    waitSaved(SEND_WAIT_MS).then(function (ok) {
      if (!ok) throw { code: "not_saved" };
      sendSay("Sending…", "busy");
      return anchor.then(function (a) { return snd.comments.sendToClaude({ anchor: a, text: sendText(S, st) }); });
    }).then(function () {
      try { localStorage.setItem(SEND_KEY, JSON.stringify({ sentAt: new Date().toISOString(), fromVersion: S.page_version })); }
      catch (e) { /* private window: the page still says Sent */ }
      snd.busy = false;
      sendBtn.disabled = false;
      sendSay(SENT_MSG, "ok");
      watchStale(staleMs(S));
    }, function (e) {
      var code = (e && e.code) || "error";
      snd.busy = false;
      sendSay(SEND_ERR[code] || (SEND_FINAL.indexOf(code) >= 0 ? "Not sent: this view can't send to Claude. Use Copy."
                                                                  : "Not sent (" + code + "). Tap again, or use Copy."), "bad");
      if (SEND_FINAL.indexOf(code) >= 0) { snd.held = true; return; }
      if (code === "rate_limited") {
        snd.held = true;
        setTimeout(function () { snd.held = false; sendBtn.disabled = false; sendCheck(); }, 60000);
        return;
      }
      sendBtn.disabled = false;
      sendCheck();
    });
  });
  (function sendOnLoad() {
    var n = pickupNote(readSent(), S, Date.now());
    if (n) {
      if (n.text) sendSay(n.text, n.tone);
      if (n.clear) { try { localStorage.removeItem(SEND_KEY); } catch (e) { /* ignore */ } }
      if (n.wait) watchStale(n.wait);
    }
  })();
  function sendConnect() {
    var c = window.claude;
    if (!sendBtn || !c || typeof c.use !== "function") return false;
    Promise.resolve().then(function () { return c.use("comments"); }).then(function (cm) {
      // null: this view cannot comment (a page published without comments, an older
      // viewer). The button stays hidden and Copy is the way, as before.
      if (!cm || typeof cm.canSendToClaude !== "function") return;
      snd.comments = cm;
      sendCheck();
    }, function () {});
    return true;
  }
  if (!sendConnect()) window.addEventListener("load", sendConnect, { once: true });
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible") sendCheck(); });
  window.addEventListener("focus", sendCheck);

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
    saveNow();
  });
  tally();
})();
