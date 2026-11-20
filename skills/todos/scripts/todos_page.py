"""Turn the open items in TODO.md into a tickable, pasteable Artifact page.

The page is written to a FIXED path -- .proofs/pages/todos.html, not a dated
one -- because the URL has to survive. Ticks live in localStorage keyed to the
page; a new file each day would reset them every morning.

Run:  python3 scripts/todos_page.py [TODO.md] [.proofs/pages/todos.html]
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from todos_parse import parse, GROUPS

MAX_TITLE = 96

# The theme and the tick/note/export machinery are COPIED from a hand-authored
# working-log page rather than shared, deliberately. That page is written by
# hand and is allowed to diverge; this one is generated and has to stay stable.
# Sharing them would mean generating the working log too -- a far larger change
# than this module justifies. Revisit if a third generated page ever appears.
CSS = r"""  :root {
    --ground:#faf8f4; --surface:#fff; --surface-2:#f2efe8;
    --border:#e3ded1; --border-strong:#cdc6b4;
    --ink:#1f1e1a; --ink-muted:#6b665b; --ink-faint:#948d7e;
    --pf-brand:#f08a54; --pf-session:#c4a7ff;
    --accent:#a35c06; --accent-soft:#fdf3e2;
    --good:#0f6f66; --good-soft:#e5f4f1;
    --warn:#a8301f; --warn-soft:#fdece9;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --shadow:0 1px 2px rgba(31,30,26,.06),0 8px 24px -16px rgba(31,30,26,.28);
  }
  @media (prefers-color-scheme:dark){:root{
    --ground:#1a1916; --surface:#22211d; --surface-2:#2a2823;
    --border:#35332c; --border-strong:#4a4740;
    --ink:#ece9e1; --ink-muted:#a09a8c; --ink-faint:#7d776b;
    --pf-brand:#c2410c; --pf-session:#6d28d9;
    --accent:#f0a422; --accent-soft:#33280f;
    --good:#4ac4b1; --good-soft:#14302c;
    --warn:#f0907e; --warn-soft:#3a201b;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.8);}}
  :root[data-theme="dark"]{
    --ground:#1a1916; --surface:#22211d; --surface-2:#2a2823;
    --border:#35332c; --border-strong:#4a4740;
    --ink:#ece9e1; --ink-muted:#a09a8c; --ink-faint:#7d776b;
    --pf-brand:#c2410c; --pf-session:#6d28d9;
    --accent:#f0a422; --accent-soft:#33280f;
    --good:#4ac4b1; --good-soft:#14302c;
    --warn:#f0907e; --warn-soft:#3a201b;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px -16px rgba(0,0,0,.8);}
  :root[data-theme="light"]{
    --ground:#faf8f4; --surface:#fff; --surface-2:#f2efe8;
    --border:#e3ded1; --border-strong:#cdc6b4;
    --ink:#1f1e1a; --ink-muted:#6b665b; --ink-faint:#948d7e;
    --pf-brand:#f08a54; --pf-session:#c4a7ff;
    --accent:#a35c06; --accent-soft:#fdf3e2;
    --good:#0f6f66; --good-soft:#e5f4f1;
    --warn:#a8301f; --warn-soft:#fdece9;
    --shadow:0 1px 2px rgba(31,30,26,.06),0 8px 24px -16px rgba(31,30,26,.28);}

  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);font-size:17px;line-height:1.6;-webkit-font-smoothing:antialiased}
  .wrap{max-width:50rem;margin:0 auto;padding:0 1.25rem 6rem}

  .projbar{position:sticky;top:0;z-index:30;background:var(--ink);color:var(--ground);border-bottom:1px solid var(--ink)}
  .projbar-inner{max-width:50rem;margin:0 auto;padding:.5rem 1.25rem;display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}
  .projbar .brand{font-family:var(--mono);font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:var(--accent)}
  .projbar .repo{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;color:var(--ground);opacity:.72}
  /* the proofs mark and skill pill, as on every proofs page; the bar is drawn in
     --ink, so its colors invert with the theme (--pf-brand, --pf-session) */
  .pf{display:inline-flex;align-items:center;gap:10px;line-height:1;white-space:nowrap;margin:-4px .3rem -4px 0}
  .pf-wm{font:600 19px/1 Georgia,Charter,"Iowan Old Style",serif;letter-spacing:-.01em;color:var(--ground)}
  .pf-wm i{color:var(--pf-brand);font-style:italic}
  .pf-sk{font:600 12.5px/1.4 var(--mono);color:var(--pf-brand);border:1px solid color-mix(in srgb,var(--pf-brand) 55%,transparent);border-radius:999px;padding:1px 9px}
  .pf-sep{width:1px;height:18px;background:color-mix(in srgb,var(--ground) 25%,transparent)}
  .pf-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
  .projbar .session{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;font-weight:700;color:var(--pf-session)}
  @media (max-width:600px){.pf-wm,.pf-sep{display:none}}
  .statusbar{position:sticky;top:2.05rem;z-index:20;background:color-mix(in srgb,var(--ground) 94%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);margin-bottom:2.5rem}
  .statusbar-inner{max-width:50rem;margin:0 auto;padding:.7rem 1.25rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
  .meter-label{font-family:var(--mono);font-size:.72rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-muted);white-space:nowrap;font-variant-numeric:tabular-nums}
  .live{display:inline-flex;align-items:center;gap:.4rem;margin-left:auto}
  .dot{width:.5rem;height:.5rem;border-radius:50%;background:var(--good)}

  header.masthead{padding:2.5rem 0 0}
  .eyebrow{font-family:var(--mono);font-size:.73rem;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0 0 1rem}
  h1{font-size:clamp(1.9rem,5vw,2.6rem);line-height:1.08;letter-spacing:-.025em;font-weight:780;margin:0 0 1rem;text-wrap:balance}
  .standfirst{font-size:1.1rem;color:var(--ink-muted);margin:0 0 1.6rem;max-width:42rem}
  .standfirst strong{color:var(--ink);font-weight:650}

  .howto{background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:1rem 1.1rem;margin-bottom:2.5rem;font-size:.93rem;color:var(--ink-muted)}
  .howto b{color:var(--ink)}
  .howto code{font-family:var(--mono);font-size:.86em;background:var(--surface);padding:.1em .35em;border-radius:4px;color:var(--ink)}

  .factbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:1px;background:var(--border);border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-bottom:3rem}
  .fact{background:var(--surface);padding:.9rem 1rem}
  .fact dt{font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);margin-bottom:.3rem}
  .fact dd{margin:0;font-family:var(--mono);font-size:.9rem;font-variant-numeric:tabular-nums}
  .fact dd.ok{color:var(--good)} .fact dd.warn{color:var(--warn)}

  .sec-head{display:flex;align-items:baseline;gap:.8rem;padding-bottom:.7rem;border-bottom:2px solid var(--ink);margin-bottom:1.3rem}
  .sec-head h2{font-size:1.25rem;font-weight:700;margin:0;flex:1;letter-spacing:-.015em}
  .sec-tag{font-family:var(--mono);font-size:.7rem;letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}

  .msg{background:var(--surface);border:1px solid var(--border);border-radius:11px;padding:1.25rem;margin-bottom:1rem;box-shadow:var(--shadow)}
  .msg.action{border-left:3px solid var(--warn)}
  .msg.done{opacity:.62}
  .msg-head{display:flex;gap:.7rem;align-items:baseline;flex-wrap:wrap;margin-bottom:.5rem}
  .msg-head h3{font-size:1.04rem;font-weight:660;margin:0;flex:1 1 15rem;line-height:1.35;letter-spacing:-.01em}
  .chip{font-family:var(--mono);font-size:.62rem;letter-spacing:.09em;text-transform:uppercase;font-weight:700;padding:.2rem .5rem;border-radius:4px;white-space:nowrap}
  .c-action{background:var(--warn-soft);color:var(--warn)}
  .c-info{background:var(--surface-2);color:var(--ink-muted)}
  .c-wait{background:var(--accent-soft);color:var(--accent)}
  .c-done{background:var(--good-soft);color:var(--good)}
  .stamp{font-family:var(--mono);font-size:.68rem;color:var(--ink-faint)}

  .msg p{margin:0 0 .7rem;font-size:.95rem;color:var(--ink-muted)}
  .msg p.lede{color:var(--ink)}
  .msg strong{color:var(--ink);font-weight:650}
  .msg code{font-family:var(--mono);font-size:.86em;background:var(--surface-2);padding:.1em .35em;border-radius:4px;color:var(--ink)}
  .msg ul{margin:0 0 .8rem;padding-left:1.1rem;font-size:.95rem;color:var(--ink-muted)}
  .msg li{margin-bottom:.3rem}
  .msg li::marker{color:var(--ink-faint)}
  .msg a{color:var(--accent);text-underline-offset:2px}

  .callout{border-left:3px solid var(--accent);background:var(--accent-soft);padding:.7rem .9rem;border-radius:0 7px 7px 0;margin:.7rem 0;font-size:.91rem;color:var(--ink)}
  .callout.bad{border-left-color:var(--warn);background:var(--warn-soft)}
  .callout.ok{border-left-color:var(--good);background:var(--good-soft)}
  .callout .lbl{font-family:var(--mono);font-size:.65rem;letter-spacing:.11em;text-transform:uppercase;font-weight:700;color:var(--accent);display:block;margin-bottom:.25rem}
  .callout.bad .lbl{color:var(--warn)}
  .callout.ok .lbl{color:var(--good)}

  .reply{margin-top:.9rem;padding-top:.85rem;border-top:1px dashed var(--border)}
  .reply-label{font-family:var(--mono);font-size:.66rem;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);display:block;margin-bottom:.45rem}
  .opts{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.55rem}
  .opt{position:relative}
  .opt input{position:absolute;opacity:0;width:0;height:0}
  .opt span{display:inline-block;font-size:.85rem;font-weight:600;padding:.42rem .75rem;border:1px solid var(--border-strong);border-radius:7px;cursor:pointer;color:var(--ink-muted);transition:all .13s}
  .opt span:hover{color:var(--ink);border-color:var(--ink-muted)}
  .opt input:checked + span{background:var(--accent);border-color:var(--accent);color:var(--ground)}
  .opt input:focus-visible + span{outline:2px solid var(--ink);outline-offset:2px}
  textarea,input[type=text]{width:100%;font-family:var(--sans);font-size:.92rem;color:var(--ink);background:var(--ground);border:1px solid var(--border);border-radius:7px;padding:.55rem .7rem;resize:vertical}
  textarea:focus,input[type=text]:focus{outline:2px solid var(--accent);outline-offset:-1px}

  .readrow{display:flex;align-items:center;gap:.55rem;margin-top:.85rem;padding-top:.7rem;border-top:1px dashed var(--border)}
  input[type=checkbox].tick{appearance:none;-webkit-appearance:none;width:1.2rem;height:1.2rem;border:2px solid var(--border-strong);border-radius:5px;background:var(--surface);cursor:pointer;display:grid;place-content:center;flex-shrink:0}
  input[type=checkbox].tick::after{content:"";width:.6rem;height:.34rem;border-left:2.5px solid var(--ground);border-bottom:2.5px solid var(--ground);transform:rotate(-45deg) translate(1px,-1px) scale(0);transition:transform .15s cubic-bezier(.3,1.6,.5,1)}
  input[type=checkbox].tick:checked{background:var(--good);border-color:var(--good)}
  input[type=checkbox].tick:checked::after{transform:rotate(-45deg) translate(1px,-1px) scale(1)}
  input[type=checkbox].tick:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  .readrow label{font-size:.87rem;color:var(--ink-muted);cursor:pointer;user-select:none}

  .export{background:var(--surface);border:2px solid var(--accent);border-radius:12px;padding:1.5rem;box-shadow:var(--shadow);margin-top:1rem}
  .export h2{margin:0 0 .4rem;font-size:1.2rem;letter-spacing:-.015em}
  .export p{color:var(--ink-muted);font-size:.94rem;margin:0 0 1.1rem}
  .btnrow{display:flex;gap:.7rem;flex-wrap:wrap}
  button.primary{font-family:var(--sans);font-size:.95rem;font-weight:640;padding:.7rem 1.3rem;border-radius:8px;border:none;background:var(--accent);color:var(--ground);cursor:pointer}
  button.primary:hover{filter:brightness(1.1)}
  button.ghost{font-family:var(--sans);font-size:.95rem;font-weight:600;padding:.7rem 1.1rem;border-radius:8px;border:1px solid var(--border-strong);background:transparent;color:var(--ink-muted);cursor:pointer}
  button.ghost:hover{color:var(--ink)}
  button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
  #out{margin-top:1.1rem;width:100%;font-family:var(--mono);font-size:.78rem;line-height:1.6;min-height:8rem;display:none;background:var(--ground);color:var(--ink);border:1px solid var(--border);border-radius:7px;padding:.6rem}
  #out.shown{display:block}

  .footnote{margin-top:3rem;padding-top:1.3rem;border-top:1px solid var(--border);font-size:.86rem;color:var(--ink-faint)}
  @media (prefers-reduced-motion:reduce){*{transition:none!important}}
  @media (max-width:34rem){body{font-size:16px}.wrap{padding:0 1rem 4rem}}

  .steps{display:flex;flex-direction:column;gap:.1rem;margin:.5rem 0 1rem}
  .step{display:flex;align-items:flex-start;gap:.65rem;padding:.55rem .7rem;border-radius:8px;cursor:pointer;font-size:.94rem;color:var(--ink);line-height:1.5}
  .step:hover{background:var(--surface-2)}
  .step span{flex:1}
  .step code{font-family:var(--mono);font-size:.85em;background:var(--surface-2);padding:.1em .35em;border-radius:4px}
  .step:hover code{background:var(--ground)}
  input[type=checkbox].stepbox{appearance:none;-webkit-appearance:none;width:1.35rem;height:1.35rem;margin-top:.05rem;border:2px solid var(--border-strong);border-radius:6px;background:var(--surface);cursor:pointer;display:grid;place-content:center;flex-shrink:0}
  input[type=checkbox].stepbox::after{content:"";width:.62rem;height:.36rem;border-left:2.5px solid var(--ground);border-bottom:2.5px solid var(--ground);transform:rotate(-45deg) translate(1px,-1px) scale(0);transition:transform .15s cubic-bezier(.3,1.6,.5,1)}
  input[type=checkbox].stepbox:checked{background:var(--good);border-color:var(--good)}
  input[type=checkbox].stepbox:checked::after{transform:rotate(-45deg) translate(1px,-1px) scale(1)}
  input[type=checkbox].stepbox:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
  .step:has(.stepbox:checked){opacity:.55}
  .step:has(.stepbox:checked) span{text-decoration:line-through;text-decoration-color:var(--ink-faint)}

  .cmdbar{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;padding:.45rem .5rem .45rem .6rem;border-bottom:1px solid var(--border);background:var(--surface)}
  .where{font-family:var(--mono);font-size:.64rem;letter-spacing:.1em;text-transform:uppercase;font-weight:700;padding:.25rem .55rem;border-radius:5px;white-space:nowrap}
  .w-any{background:var(--surface-2);color:var(--ink-muted)}
  .cmdnote{font-size:.78rem;color:var(--ink-faint);flex:1 1 8rem;line-height:1.35}
  .chip[data-secprog]{background:var(--surface-2);color:var(--ink-muted);font-variant-numeric:tabular-nums}
  .chip[data-secprog].full{background:var(--good-soft);color:var(--good)}
  .msg.action:has(.stepbox):not(:has(.stepbox:not(:checked))){border-left-color:var(--good)}

  /* Always reachable: people work through this page on a phone and were scrolling
     past finished cards to find the export. Lives in the sticky bar, so it is on
     screen at every scroll position. */
  .copytop{margin-left:auto;font-family:var(--sans);font-size:.8rem;font-weight:640;padding:.4rem .8rem;border-radius:7px;border:none;background:var(--accent);color:var(--ground);cursor:pointer;white-space:nowrap}
  .copytop:hover{filter:brightness(1.1)}
  .copytop:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
  .copytop.done{background:var(--good)}
  @media (max-width:34rem){
    .copytop{font-size:.75rem;padding:.35rem .6rem}
    .statusbar-inner{gap:.6rem}
  }

  .sizes{width:100%;border-collapse:collapse;margin:.8rem 0 1rem;font-size:.9rem}
  .sizes th{text-align:left;font-family:var(--mono);font-size:.66rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink-faint);border-bottom:1px solid var(--border-strong);padding:.4rem .5rem}
  .sizes td{padding:.42rem .5rem;border-bottom:1px solid var(--border);color:var(--ink-muted)}
  .sizes td:nth-child(2){font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink);white-space:nowrap}
  .sizes tr.no td{color:var(--ink-faint)}
  .sizes tr:last-child td{border-bottom:none}

  /* The note field sits INSIDE the step's <label> purely for layout. No JS
     guard is needed: per the HTML spec, a label's activation behavior does
     nothing for events targeted at an interactive-content descendant, and a
     text input is one -- clicking or typing in it never ticks the box. */
  .step input[type=text]{display:block;width:100%;margin-top:.45rem;font-size:.84rem;
    padding:.35rem .5rem;border:1px solid var(--border);border-radius:6px;
    background:var(--ground);color:var(--ink)}
  .step input[type=text]:placeholder-shown{opacity:.55}
  .step input[type=text]:focus{opacity:1;outline:2px solid var(--accent);outline-offset:-1px}
  .step:has(.stepbox:checked) input[type=text]{opacity:1}
  .step:has(.stepbox:checked) span b{text-decoration:line-through;text-decoration-color:var(--ink-faint)}
  .step:has(.stepbox:checked) span{text-decoration:none}"""

# Lifted from that page's <script> minus its message-card specifics (the
# OPTIONS map and the read-tick/data-read machinery -- this page has no
# message cards to read or answer). The stepbox, stepnote, counter and export
# halves are kept whole. An earlier stopPropagation guard on [data-stepnote]
# was removed 2026-08-06: it defended against a click/keystroke in the note
# field ticking the item, which cannot happen (see the note-field comment
# below) and which stopPropagation could not have prevented even if it did.
#
# Two deliberate departures from that verbatim copy, both load-bearing:
#   - KEY is page-specific ("ember-todos-v1"), not reused from the working
#     log. Both pages can render items with the same t1/t2/... ids; sharing a
#     localStorage key would cross-contaminate their tick state.
#   - build()'s per-item export line prefers a full, untruncated data-title
#     attribute over scraping the (possibly 96-char-clipped) label text --
#     see _item_row below. Task 6 matches an exported line back to a real
#     item by its title, and a display clip must never be what travels in
#     the paste.
SCRIPT = r"""(function(){
  'use strict';
  var KEY='ember-todos-v1';

  var state={};
  try{state=JSON.parse(localStorage.getItem(KEY)||'{}');}catch(e){state={};}
  function save(){try{localStorage.setItem(KEY,JSON.stringify(state));}catch(e){}}

  state.__steps=state.__steps||{};

  var steps=Array.prototype.slice.call(document.querySelectorAll('input.stepbox[data-step]'));
  steps.forEach(function(box){
    var id=box.dataset.step;
    if(state.__steps[id])box.checked=true;
    box.addEventListener('change',function(){
      state.__steps[id]=box.checked; save(); refresh();
    });
  });

  // A per-item note, so an item can come back as "done, but ..." rather than
  // only as a tick. It lives INSIDE the step's <label> for layout only. No
  // guard is needed to stop a note field ticking the item it explains: per
  // the HTML spec a label's activation behavior does nothing for events
  // targeted at interactive-content descendants, and a text input is one --
  // verified in jsdom 2026-08-06, where clicking the label's own text ticks
  // the box and clicking the nested input does not. An earlier
  // stopPropagation guard here was inert twice over: the behavior does not
  // occur, and stopPropagation could not have prevented it if it did (only
  // preventDefault on a cancelable event could). Do not re-add one.
  state.__stepnotes=state.__stepnotes||{};
  document.querySelectorAll('[data-stepnote]').forEach(function(n){
    var id=n.dataset.stepnote;
    if(state.__stepnotes[id])n.value=state.__stepnotes[id];
    n.addEventListener('input',function(){
      state.__stepnotes[id]=n.value; save();
    });
  });

  var free=document.getElementById('freeform');
  if(state.__free)free.value=state.__free;
  free.addEventListener('input',function(){state.__free=free.value;save();});

  function refresh(){
    var sdone=steps.filter(function(b){return b.checked;}).length;
    var meter=document.getElementById('stepcount');
    if(meter)meter.textContent=sdone+' / '+steps.length+' done';

    // Per-section counters, so a group reads as "2 / 5" on its own header
    // rather than only as a share of one intimidating total. Counted from the
    // chip's OWN group container -- mirrors the working log's per-card
    // counters, scoped to .group instead of .msg because this page's
    // sections are plain divs, not message cards.
    document.querySelectorAll('[data-secprog]').forEach(function(chip){
      var card=chip.closest('.group');
      var mine=card?Array.prototype.slice.call(card.querySelectorAll('input.stepbox')):[];
      var n=mine.filter(function(b){return b.checked;}).length;
      chip.textContent=n+' / '+mine.length;
      chip.classList.toggle('full',mine.length>0&&n===mine.length);
    });
  }

  function build(){
    var lines=['TODOS — my replies',''];
    if(steps.length){
      var sdone=steps.filter(function(b){return b.checked;}).length;
      lines.push('OPEN ITEMS — '+sdone+' / '+steps.length+' done');
      var lastSec=null;
      steps.forEach(function(box){
        // Group by the step's OWN data-sec.
        var sec=box.dataset.sec||'';
        if(sec!==lastSec){lines.push('','  '+sec);lastSec=sec;}
        // The FULL title, not the (possibly truncated for display) label
        // text -- an exported line is matched back to a real item by its
        // title, and a 96-char display clip must never be what travels in
        // the paste.
        var text=box.dataset.title||'';
        if(!text){
          var label=box.parentElement.querySelector('span');
          if(label){
            label.childNodes.forEach(function(n){
              if(n.nodeName!=='INPUT')text+=(n.textContent||'');
            });
          }
          text=text.replace(/\s+/g,' ').trim();
          if(text.length>96)text=text.slice(0,93)+'...';
        }
        lines.push('    ['+(box.checked?'x':' ')+'] '+text);
        var sn=state.__stepnotes[box.dataset.step];
        if(sn&&sn.trim())lines.push('          note: '+sn.trim());
      });
    } else {
      lines.push('OPEN ITEMS — none');
    }
    if(state.__free&&state.__free.trim()){lines.push('','Anything else:',state.__free.trim());}
    return lines.join('\n');
  }

  // http on a LAN address is not a secure context: no clipboard. A failed
  // write is the same. Try the old copy command; if that fails too, show the
  // text in a box to select. "Copied" is only ever shown after a real copy.
  function fallback(text,done,btn){
    var ta=document.createElement('textarea');
    ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    var ok=false;
    try{ok=!!document.execCommand('copy');}catch(e){}
    document.body.removeChild(ta);
    if(ok){if(done)done();return;}
    var box=document.querySelector('textarea[data-copy-fallback]');
    if(!box){
      box=document.createElement('textarea');
      box.setAttribute('data-copy-fallback','');box.readOnly=true;box.rows=10;
      box.setAttribute('aria-label','Replies to copy');
      box.style.cssText='display:block;width:100%;box-sizing:border-box;margin-top:10px;font:inherit;padding:10px';
      var anchor=document.getElementById('copy');
      anchor.parentNode.insertBefore(box,anchor.nextSibling);
    }
    box.value=text;box.focus();box.select();
    if(btn)btn.textContent='Select all and copy from the box';
  }

  function copyText(text,done,btn){
    if(navigator.clipboard&&navigator.clipboard.writeText){
      try{navigator.clipboard.writeText(text).then(done,function(){fallback(text,done,btn);});}
      catch(e){fallback(text,done,btn);}
    } else {fallback(text,done,btn);}
  }

  document.getElementById('copy').addEventListener('click',function(){
    var b=this;
    copyText(build(),function(){
      b.textContent='Copied \u2014 paste it into chat';
      setTimeout(function(){b.textContent='Copy my replies';},2600);
    },b);
  });

  // Always reachable: an 18-item checklist is longer than one screen, and a
  // phone reader scrolling to find "Copy my replies" at the bottom is the
  // exact problem this button solves. Lives in the sticky status bar, so it
  // is on screen at every scroll position. Same build() as the button at the
  // foot of the page -- two entry points, one build(), so they can never
  // disagree about what was copied.
  var topBtn=document.getElementById('copytop');
  if(topBtn){
    topBtn.addEventListener('click',function(){
      copyText(build(),function(){
        topBtn.textContent='Copied';topBtn.classList.add('done');
        setTimeout(function(){topBtn.textContent='Copy my replies';topBtn.classList.remove('done');},2200);
      },null);
    });
  }

  document.getElementById('show').addEventListener('click',function(){
    var o=document.getElementById('out'); o.value=build(); o.classList.toggle('shown');
  });

  document.getElementById('reset').addEventListener('click',function(){
    state={__steps:{},__stepnotes:{}};save();
    document.querySelectorAll('input.stepbox[data-step]').forEach(function(b){b.checked=false;});
    document.querySelectorAll('[data-stepnote]').forEach(function(n){n.value='';});
    free.value=''; refresh();
  });

  refresh();
})();"""


def esc(text):
    """Escape for both element text and attribute values."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


def _item_row(item):
    title = item["title"]
    if len(title) > MAX_TITLE:
        title = title[:MAX_TITLE - 3] + "..."
    # Untruncated "N. Title", carried on the checkbox as data-title so the
    # export can quote the item in full regardless of the display clip above.
    full_title = "%d. %s" % (item["n"], item["title"])
    return (
        '<label class="step">'
        '<input type="checkbox" class="stepbox" data-step="%s" data-sec="%s" data-title="%s">'
        '<span><b>%d. %s</b> %s'
        '<input type="text" data-stepnote="%s" placeholder="Note (optional)">'
        '</span></label>'
    ) % (esc(item["id"]), esc(item["group"]), esc(full_title), item["n"], esc(title),
         esc(item["body"].split("\n")[0][:160]), esc(item["id"]))


def _banner(unparsed):
    if not unparsed:
        return ""
    rows = "".join(
        '<li><code>line %d</code> — %s <em>(%s)</em></li>'
        % (u["line"], esc(u["text"][:120]), esc(u["why"]))
        for u in unparsed)
    return (
        '<div class="callout bad"><span class="lbl">%d lines could not be parsed'
        '</span>These look like work and are <b>not</b> on the list below. '
        'Fix them in <code>TODO.md</code> — the count is not trustworthy until '
        'this is empty.<ul>%s</ul></div>' % (len(unparsed), rows))


PAGE = """<title>Todos &middot; %(project)s</title>
<style>
%(css)s
</style>

<div class="projbar">
  <div class="projbar-inner">
    <span class="pf"><span class="pf-wm" aria-hidden="true">pro<i>o</i>fs</span><span class="pf-sk" aria-hidden="true">todos</span><span class="pf-sr">Proofs, todos</span><span class="pf-sep" aria-hidden="true"></span></span>
    <span class="brand">%(project)s</span>%(session)s
    <span class="repo">%(repo)s</span>
  </div>
</div>

<div class="statusbar">
  <div class="statusbar-inner">
    <span class="meter-label">%(count)s</span>
    <span class="meter-label" id="stepcount">%(stepinit)s</span>
    <button class="copytop" type="button" id="copytop">Copy my replies</button>
  </div>
</div>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">Open items &middot; generated from TODO.md</p>
    <h1>Tick what you have done, then copy your replies back</h1>
    <p class="standfirst">
      <strong>Every open item, in the order TODO.md carries them.</strong>
      Tick what is done, add a note if there is anything to say, then use
      <strong>Copy my replies</strong> below and paste it back into chat.
    </p>
  </header>

  %(banner)s

  %(groups)s

  <section class="export">
    <h2>Copy my replies</h2>
    <p>Your ticks, your notes and anything you typed. Paste it back into chat.</p>
    <div class="btnrow">
      <button class="primary" type="button" id="copy">Copy my replies</button>
      <button class="ghost" type="button" id="show">Show the text</button>
      <button class="ghost" type="button" id="reset">Reset</button>
    </div>
    <label class="reply-label" style="margin-top:1.1rem">Anything else</label>
    <textarea id="freeform" rows="3" placeholder="Anything at all"></textarea>
    <textarea id="out" rows="12" readonly aria-label="Your replies, as text"></textarea>
  </section>
</div>
<script>
%(script)s
</script>
"""


def render(data, project, repo, session=None):
    items, unparsed = data["items"], data["unparsed"]
    count = "%d open" % len(items)
    if unparsed:
        count += " &middot; %d unparsed" % len(unparsed)
    groups_html = []
    for group in GROUPS:
        rows = [_item_row(i) for i in items if i["group"] == group]
        if not rows:
            continue
        groups_html.append(
            '<div class="group"><div class="sec-head"><h2>%s</h2>'
            '<span class="chip" data-secprog>0 / %d</span></div>'
            '<div class="steps">%s</div></div>'
            % (esc(group), len(rows), "".join(rows)))
    return PAGE % {
        "css": CSS, "script": SCRIPT, "project": esc(project), "repo": esc(repo),
        "session": '\n    <span class="session">%s</span>' % esc(session) if session else "",
        "count": count, "stepinit": "0 / %d done" % len(items), "banner": _banner(unparsed),
        "groups": "".join(groups_html) or "<p>Nothing open.</p>",
    }


def build(todo_path, out_path, project, repo, session=None):
    with open(todo_path, encoding="utf-8") as handle:
        data = parse(handle.read())
    html = render(data, project, repo, session)
    folder = os.path.dirname(out_path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return html


class UnknownIdentity(RuntimeError):
    """The project name or repo slug could not be derived, and neither was
    given explicitly. Raised rather than guessed: the project bar exists so
    two projects' pages are never mistakable for one another, and a
    plausible-looking wrong label is worse than a refusal, because nobody
    double-checks a label that looks right."""


def _git_remote_url(cwd="."):
    """`git remote get-url origin`, or None if it fails for any reason --
    no remote named origin, not a git checkout at all, git not installed."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# Matches both forms git remotes actually come in:
#   SSH:   git@example.com:owner/name.git
#   HTTPS: https://github.com/owner/name.git
_SSH_REMOTE_RE = re.compile(r"^[\w.\-]+@[\w.\-]+:(?P<path>.+?)/*$")
_HTTPS_REMOTE_RE = re.compile(r"^\w+://[^/]+/(?P<path>.+?)/*$")


def _repo_slug_from_url(url):
    """A git remote URL, in either SSH or HTTPS form, with or without a
    trailing .git, reduced to "owner/name". None if it doesn't parse."""
    if not url:
        return None
    match = _SSH_REMOTE_RE.match(url.strip()) or _HTTPS_REMOTE_RE.match(url.strip())
    if not match:
        return None
    path = match.group("path")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts[-2:])


def _repo_slug(cwd="."):
    return _repo_slug_from_url(_git_remote_url(cwd))


def _project_name_from_claude_md(text):
    """The bolded name on the "About This App" line -- e.g. "**Acme
    Tracker**" -- searched only within that section, so an unrelated bold
    phrase in a later section can never be mistaken for the project name."""
    heading = re.search(r"^##\s+About This App\s*$", text, re.MULTILINE)
    if not heading:
        return None
    section = text[heading.end():]
    next_heading = re.search(r"^##\s+", section, re.MULTILINE)
    if next_heading:
        section = section[:next_heading.start()]
    bold = re.search(r"\*\*(.+?)\*\*", section)
    return bold.group(1).strip() if bold else None


def _project_name(claude_md_path):
    try:
        with open(claude_md_path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    return _project_name_from_claude_md(text)


def resolve_identity(argv, cwd="."):
    """(project, repo) -- argv[3]/argv[4] if given explicitly, otherwise
    derived from this repo's own CLAUDE.md and `git remote get-url origin`.
    Never guessed and never defaulted to any other project's name: raises
    UnknownIdentity naming exactly what could not be determined and how to
    supply it explicitly on the command line.

    Project name has two derivations, tried in order, and they are NOT
    interchangeable in kind:
      1. CLAUDE.md's "About This App" bold name -- an explicit, authored
         label.
      2. The repo's own name, taken from the slug already derived from git
         remote (the part after the last "/"). This is legitimate where
         guessing a name out of arbitrary prose is not: it isn't invented,
         it's the same source of truth already parsed for the repo slug,
         just its last segment. Being redundant next to the repo slug in
         the project bar is fine -- the bar exists so two projects' pages
         are never mistaken for each other, and a repo name discharges
         that completely on its own.
    Only if NEITHER resolves does this fail loud.
    """
    repo = argv[4] if len(argv) > 4 else _repo_slug(cwd)
    if len(argv) > 3:
        project = argv[3]
    else:
        project = _project_name(os.path.join(cwd, "CLAUDE.md"))
        if not project and repo:
            project = repo.split("/")[-1]
    missing = []
    if not project:
        missing.append(
            "the project name (no \"**Name**\" found under \"## About This "
            "App\" in CLAUDE.md, and no repo name to fall back on either "
            "since the repo slug also couldn't be derived -- pass it as "
            "the 3rd argument)")
    if not repo:
        missing.append(
            "the repo slug (`git remote get-url origin` did not resolve to "
            "an owner/name pair -- pass it as the 4th argument)")
    if missing:
        raise UnknownIdentity("Could not derive: " + "; ".join(missing))
    return project, repo


DEFAULT_OUT = ".proofs/pages/todos.html"


def take_session(argv):
    """(argv without `--session NAME`, NAME or None): the session's name is a flag,
    so it can be given without spelling out the positional project and repo."""
    if "--session" not in argv:
        return list(argv), None
    i = argv.index("--session")
    if i + 1 >= len(argv):
        raise SystemExit("--session needs a name")
    return argv[:i] + argv[i + 2:], argv[i + 1]


def main(argv):
    argv, session = take_session(argv)
    if not session:
        print("warning: no --session: the reader can't tell which session this page belongs to", file=sys.stderr)
    todo_path = argv[1] if len(argv) > 1 else "TODO.md"
    out_path = argv[2] if len(argv) > 2 else DEFAULT_OUT
    project, repo = resolve_identity(argv)
    build(todo_path, out_path, project, repo, session)
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
