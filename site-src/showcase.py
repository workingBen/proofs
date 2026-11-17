"""Before/after sliders and step-throughs, built from site-src/examples.json.

examples.json is written by import_examples.py. When it is missing the site builds
without any showcase, and none of this CSS or JS is added to the pages.
Set PROOFS_EXAMPLES to read another file (the tests do).
"""
import html
import json
import os

e = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    path = os.environ.get("PROOFS_EXAMPLES") or os.path.join(HERE, "examples.json")
    if not os.path.isfile(path):
        return []
    return json.load(open(path, encoding="utf-8")).get("examples", [])


def out_dir():
    return os.environ.get("PROOFS_SITE_OUT") or os.path.join(os.path.dirname(HERE), "docs")


def _pic(x, fr, sizes, eager, alt):
    base = f'examples/{x["id"]}/{fr["name"]}'
    ws = fr["widths"]
    ss = lambda ext: ", ".join(f"{base}-{w}.{ext} {w}w" for w in ws)
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<picture><source type="image/webp" srcset="{ss("webp")}" sizes="{sizes}">'
            f'<img src="{base}-{ws[-1]}.jpg" srcset="{ss("jpg")}" sizes="{sizes}" width="{x["w"]}" height="{x["h"]}" '
            f'alt="{e(alt)}" {load} decoding="async" draggable="false"></picture>')


def _frame(x, name):
    return next((f for f in x["frames"] if f["name"] == name), None)


def _sizes(x, big):
    if big:
        return "(min-width: 960px) 680px, 100vw"
    return "320px" if x["view"] == "phone" else "(min-width: 900px) 560px, 100vw"


KNOB = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l-6 6 6 6M15 6l6 6-6 6"/></svg>')


def slider(x, big=False, eager=False):
    """One before/after slider. Before is on the left of the line, After on the right."""
    b, a = _frame(x, "before") or x["frames"][0], _frame(x, "after") or x["frames"][-1]
    sz = _sizes(x, big)
    return (f'<div class="ba{" big" if big else ""} v-{e(x["view"])}" data-ba style="--p:.5;aspect-ratio:{x["w"]}/{x["h"]}" '
            f'role="slider" tabindex="0" aria-label="{e(x["title"])}: drag to compare before and after" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="50" aria-valuetext="50% after">'
            f'<div class="ba-img">{_pic(x, b, sz, eager, b["label"])}</div>'
            f'<div class="ba-img ba-after">{_pic(x, a, sz, eager, a["label"])}</div>'
            f'<span class="ba-lbl l">{e(b["label"])}</span><span class="ba-lbl r">{e(a["label"])}</span>'
            f'<span class="ba-line" aria-hidden="true"><span class="ba-knob">{KNOB}</span></span></div>')


def stepper(x, eager=False):
    """Three or more frames that advance on their own, with a button per step."""
    sz = _sizes(x, True)
    imgs = "".join(f'<div class="st-img{" on" if i == 0 else ""}">{_pic(x, f, sz, eager and i == 0, f["label"])}'
                   f'<span class="ba-lbl l{" r" if i == len(x["frames"]) - 1 else ""}">{e(f["label"])}</span></div>'
                   for i, f in enumerate(x["frames"]))
    btns = "".join(f'<button type="button" class="st-b{" on" if i == 0 else ""}" aria-pressed="{"true" if i == 0 else "false"}">'
                   f'<span class="st-n">{i + 1:02d}</span>{e(f["label"])}<i class="st-bar"></i></button>'
                   for i, f in enumerate(x["frames"]))
    return (f'<div class="steps v-{e(x["view"])}" data-steps>'
            f'<div class="st-stage" style="aspect-ratio:{x["w"]}/{x["h"]}" aria-live="polite">{imgs}</div>'
            f'<div class="st-row" role="group" aria-label="{e(x["title"])}: steps">{btns}</div></div>')


def component(x, big=False, eager=False):
    return stepper(x, eager) if len(x["frames"]) > 2 else slider(x, big, eager)


def card(x, n, link=True):
    sk = (f'<a class="bx-skill" href="{e(x["skill"])}.html">{e(x["skill"])}{ARROW}</a>' if link
          else f'<span class="bx-skill">{e(x["skill"])}</span>')
    return (f'<figure class="bx v-{e(x["view"])}" id="ex-{e(x["id"])}">{component(x)}'
            f'<figcaption><span class="fn">{n:02d}</span><h3>{e(x["title"])}</h3>'
            f'<p class="sub">{e(x["caption"])}</p>{sk}</figcaption></figure>')


ARROW = ('<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8" '
         'aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"/></svg>')


def gallery(items, start=1, link=True):
    return '<div class="bx-grid">' + "".join(card(x, start + i, link) for i, x in enumerate(items)) + "</div>"


CSS = '''
/* before/after showcase */
.ba{position:relative;width:100%;overflow:hidden;border-radius:12px;border:1px solid var(--line);background:var(--card);
  touch-action:pan-y;user-select:none;-webkit-user-select:none;cursor:ew-resize;outline:none;box-shadow:0 1px 0 var(--line)}
.ba:focus-visible{box-shadow:0 0 0 3px var(--accent)}
.ba-img,.ba-img picture,.ba-img img{position:absolute;inset:0;width:100%;height:100%;display:block}
.ba-img img{object-fit:cover;object-position:top;pointer-events:none}
.ba-after{clip-path:inset(0 0 0 calc(var(--p) * 100%))}
.ba-line{position:absolute;top:0;bottom:0;left:calc(var(--p) * 100%);width:2px;margin-left:-1px;background:#fff;
  box-shadow:0 0 0 1px rgba(0,0,0,.25);pointer-events:none}
.ba-knob{position:absolute;top:50%;left:50%;width:40px;height:40px;margin:-20px 0 0 -20px;border-radius:50%;
  background:var(--accent);color:#fff;display:grid;place-items:center;box-shadow:0 2px 10px rgba(0,0,0,.3)}
.ba-lbl{position:absolute;top:10px;font:600 11px/1 "JetBrains Mono",monospace;letter-spacing:.06em;text-transform:uppercase;
  padding:6px 9px;border-radius:999px;background:rgba(20,18,15,.78);color:#fff;pointer-events:none;
  max-width:calc(50% - 16px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:opacity .12s linear}
.ba-lbl.l{left:10px} .ba-lbl.r{right:10px;background:var(--accent)} .st-img .ba-lbl.r{right:auto}
.ba.v-phone,.steps.v-phone .st-stage{aspect-ratio:16/10!important;background:var(--soft)}
.ba.v-phone .ba-img img,.steps.v-phone .st-img img{object-fit:contain;object-position:center}
.steps{display:grid;gap:10px}
.st-stage{position:relative;width:100%;overflow:hidden;border-radius:12px;border:1px solid var(--line);background:var(--card)}
.st-img{position:absolute;inset:0;opacity:0;transition:opacity .6s ease}
.st-img.on{opacity:1}
.st-img picture,.st-img img{display:block;width:100%;height:100%}
.st-img img{object-fit:cover;object-position:top}
.st-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(0,1fr));gap:6px}
.st-b{position:relative;display:flex;gap:6px;align-items:baseline;text-align:left;overflow:hidden;font:600 13px/1.25 -apple-system,sans-serif;
  color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:9px;padding:10px 10px 12px;min-height:44px;cursor:pointer}
.st-b.on{border-color:var(--accent)}
.st-n{font:600 11px "JetBrains Mono",monospace;color:var(--accent)}
.st-bar{position:absolute;left:0;bottom:0;height:3px;width:0;background:var(--accent)}
.st-b.on .st-bar{width:var(--t,100%)}
.bx-grid{columns:2;column-gap:18px}
.bx-grid>.bx{break-inside:avoid;margin-bottom:18px}
.bx{margin:0;display:grid;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
.bx figcaption{display:grid;gap:4px;padding:0 4px 4px;min-width:0}
.bx h3{margin:0;font:400 28px/1.08 "Instrument Serif",Georgia,serif;text-wrap:balance}
.bx .sub{margin:0;color:var(--muted);font-size:16px;line-height:1.4}
.bx-skill{display:inline-flex;gap:6px;align-items:center;width:fit-content;margin-top:4px;font:600 12.5px "JetBrains Mono",monospace;
  color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:5px 11px;min-height:32px}
a.bx-skill:hover{border-color:var(--accent)}
.showcase{padding-block:8px 40px}
.showcase .lede{display:grid;gap:6px;margin-bottom:18px}
.showcase .lede h2{font:400 40px/1.1 "Instrument Serif",Georgia,serif;margin:0}
.showcase .lede p{margin:0;font-size:18px;font-weight:650;line-height:1.35;max-width:40em}
@media (max-width:900px){.bx-grid{columns:1}}
@media (max-width:440px){.bx{padding:10px}.bx h3{font-size:25px}.ba-lbl{font-size:10px;padding:5px 7px}.st-b{font-size:12px;padding:8px 8px 11px}}
@media (prefers-reduced-motion:reduce){.st-img{transition:none}}
'''

# One small script for every slider and step-through on the page. No libraries.
JS = r'''
<script>
(function(){
  var RM = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var IO = 'IntersectionObserver' in window;
  function ease(t){return t<.5?4*t*t*t:1-Math.pow(-2*t+2,3)/2}
  /* A label shows in full while its side fills most of the frame (FADE_HI or more)
     and is gone by FADE_LO, so the label always names the picture you see. */
  var FADE_LO=.35, FADE_HI=.65;
  function fade(share){ var t=Math.max(0,Math.min(1,(share-FADE_LO)/(FADE_HI-FADE_LO))); return t*t*(3-2*t); }
  /* Auto-sweep: hold on Before, sweep to After, hold, sweep back. */
  var LO=.03, HI=.97, HOLD_B=1100, SWEEP=1700, HOLD_A=1500, CYCLE=HOLD_B+SWEEP+HOLD_A+SWEEP;
  function at(t){
    t%=CYCLE;
    if(t<HOLD_B) return HI;
    t-=HOLD_B; if(t<SWEEP) return HI-(HI-LO)*ease(t/SWEEP);
    t-=SWEEP; if(t<HOLD_A) return LO;
    t-=HOLD_A; return LO+(HI-LO)*ease(t/SWEEP);
  }
  [].forEach.call(document.querySelectorAll('[data-ba]'), function(el){
    var l=el.querySelector('.ba-lbl.l'), r=el.querySelector('.ba-lbl.r');
    var auto=!RM, run=false, raf=0, cur=.5;
    function set(p){
      p=Math.max(0,Math.min(1,p)); cur=p;
      el.style.setProperty('--p',p);
      var v=Math.round((1-p)*100);
      el.setAttribute('aria-valuenow',v); el.setAttribute('aria-valuetext',v+'% after');
      l.style.opacity=fade(p); r.style.opacity=fade(1-p);
    }
    /* One clock for the whole page, so every slider sweeps in step with the others. */
    function tick(now){ if(!run) return; set(at(now)); raf=requestAnimationFrame(tick); }
    function start(){ if(!auto||run) return; run=true; raf=requestAnimationFrame(tick); }
    function stop(){ run=false; cancelAnimationFrame(raf); }
    function grab(){ auto=false; stop(); el.classList.add('held'); }
    if(auto){
      set(HI);
      if(IO){ new IntersectionObserver(function(es){es.forEach(function(en){en.isIntersecting?start():stop()})},{threshold:.35}).observe(el); }
      else start();
    } else { set(.5); l.style.opacity=1; r.style.opacity=1; }
    function fromX(x){ var b=el.getBoundingClientRect(); set((x-b.left)/b.width); }
    var drag=false;
    el.addEventListener('pointerdown',function(ev){ grab(); drag=true; try{el.setPointerCapture(ev.pointerId)}catch(_){} fromX(ev.clientX); });
    el.addEventListener('pointermove',function(ev){ if(drag) fromX(ev.clientX); });
    function up(){ drag=false; }
    el.addEventListener('pointerup',up); el.addEventListener('pointercancel',up);
    el.addEventListener('keydown',function(ev){
      var p=cur, k=ev.key, step=null;
      if(k==='ArrowLeft'||k==='ArrowDown') step=-.05; else if(k==='ArrowRight'||k==='ArrowUp') step=.05;
      else if(k==='PageDown') step=-.2; else if(k==='PageUp') step=.2;
      else if(k==='Home'){ grab(); set(1); ev.preventDefault(); return; }
      else if(k==='End'){ grab(); set(0); ev.preventDefault(); return; }
      if(step===null) return;
      /* The value counts how much After shows, so Right or Up shows more of it. */
      grab(); set(p-step); ev.preventDefault();
    });
  });
  [].forEach.call(document.querySelectorAll('[data-steps]'), function(el){
    var imgs=el.querySelectorAll('.st-img'), btns=el.querySelectorAll('.st-b'), n=imgs.length;
    var i=0, auto=!RM, run=false, raf=0, t0=0, el0=0, STEP=2600;
    function show(k){
      i=(k+n)%n;
      for(var j=0;j<n;j++){ imgs[j].classList.toggle('on',j===i); btns[j].classList.toggle('on',j===i); btns[j].setAttribute('aria-pressed',j===i?'true':'false'); btns[j].style.removeProperty('--t'); }
    }
    function tick(now){
      if(!run) return; var d=now-t0;
      if(d>=STEP){ show(i+1); t0=now; d=0; }
      btns[i].style.setProperty('--t',(d/STEP*100)+'%'); el0=d;
      raf=requestAnimationFrame(tick);
    }
    function start(){ if(!auto||run) return; run=true; t0=performance.now()-el0; raf=requestAnimationFrame(tick); }
    function stop(){ run=false; cancelAnimationFrame(raf); }
    [].forEach.call(btns,function(b,k){ b.addEventListener('click',function(){ auto=false; stop(); show(k); }); });
    if(auto){
      if(IO){ new IntersectionObserver(function(es){es.forEach(function(en){en.isIntersecting?start():stop()})},{threshold:.35}).observe(el); }
      else start();
    }
  });
})();
</script>
'''
