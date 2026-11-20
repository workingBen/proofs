import html, json, os, re, shutil
from site_order import GROUPS
import showcase
e = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))
tpl = open(os.path.join(HERE, "skillpage_tpl.html")).read()
style = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1).replace("%%EXCSS%%", "")
links = tpl[:tpl.index("<style>")].replace("<title>proofs · %%SKILL%%</title>", "<title>proofs</title>")

# Top picks: a "Top pick" tag on the left, a ribbon on the right.
TOP = {"design-review": "Start here", "pr-qa": "Critical for UI changes", "working-log": "Most used"}
STAR = ('<svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor" aria-hidden="true">'
        '<path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3 6.1 20.6l1.3-6.6L2.5 9.4l6.6-.8z"/></svg>')
cards, total_f, n_sk = "", 0, 0
for gi, (gname, skills) in enumerate(GROUPS):
    items = ""
    for s in sorted(skills, key=lambda k: k not in TOP):  # top picks lead their section
        p = os.path.join(HERE, "pages", f"{s}.json")
        if not os.path.exists(p):
            items += f'<div class="sk-card wait"><b>{e(s)}</b><span>Page coming</span></div>'
            continue
        d = json.load(open(p))
        feats = [f for sec in d["sections"] for f in sec["features"]]
        total_f += len(feats); n_sk += 1
        chips = "".join(f'<span>{e(f.get("label", f["title"]))}</span>' for f in feats[:4])
        top = (f'<span class="sk-pick">{STAR}Top pick</span><span class="sk-ribbon">{e(TOP[s])}</span>' if s in TOP else "")
        pic = (f'<img class="sk-pic" src="cards/{e(s)}.jpg" width="780" height="300" alt="" loading="lazy">'
               if os.path.exists(os.path.join(showcase.out_dir(), "cards", f"{s}.jpg")) else "")
        items += f'''<a class="sk-card{' top' if s in TOP else ''}" href="{e(s)}.html">{top}<div class="sk-top"><b>{e(s)}</b><em>{len(feats)} features</em></div>
<p class="sk-tag">{e(d["tagline"])}</p><div class="sk-chips">{chips}{f'<span class="more">+{len(feats)-4} more</span>' if len(feats) > 4 else ''}</div>{pic}</a>'''
    cards += f'<section class="grp"><h3><span>{gi+1:02d}</span>{e(gname)}</h3><div class="sk-grid">{items}</div></section>'

exs = showcase.load()
hero = next((x for x in exs if x["use"] == "hero" and len(x["frames"]) == 2), None)
steps = next((x for x in exs if x["use"] == "hero" and len(x["frames"]) > 2), None)
feat = [x for x in exs if x["use"] == "featured"]
# The hero's right column: the one-minute Short, behind our own cover. Nothing loads from YouTube
# until the play button is pressed; then the button is swapped for a youtube-nocookie iframe.
VIDEO_ID = "LGoRROsziv8"
MEDIA = os.path.join(HERE, "media")
PLAY = ('<svg viewBox="0 0 24 24" width="34" height="34" fill="currentColor" aria-hidden="true">'
        '<path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.6-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>')
hero_vid = (f'<figure class="hero-vid"><div class="vid" data-yt="{VIDEO_ID}">'
            '<button type="button" class="vid-play" aria-label="Play the one-minute Proofs video (loads YouTube)">'
            '<picture><source type="image/webp" srcset="media/proofs-short-cover.webp">'
            '<img src="media/proofs-short-cover.jpg" width="720" height="720" alt="" loading="eager" fetchpriority="high" decoding="async"></picture>'
            f'<span class="vid-knob">{PLAY}</span></button></div>'
            '<figcaption><b>Watch Proofs at work.</b> One minute, start to finish. '
            'Nothing loads from YouTube until you press play.</figcaption></figure>')
show = ""
if feat or steps:
    # Every example in ORDER, so the best come first; the retreat pair (once the hero slider) leads.
    items = ([hero] if hero else []) + [x for x in exs if x is not hero and x["use"] != "skill"]
    show = ('<section class="in showcase" id="examples"><div class="lede"><div class="eyebrow">Real work, before and after</div>'
            '<h2>See it work</h2><p>Each pair is a real page before and after one review. They slide on their own. Drag any of them.</p></div>'
            + showcase.featured(items)
            # From the 2026-11-19 design review: one quiet, full-width line after the gallery saying
            # where the real examples come from.
            + '<p class="gs-note">Every example here is real work from my own business, '
              '<a href="https://greensprings.life" target="_blank" rel="noopener">'
              'Greensprings Longevity\u00a0\u2197</a>.</p>')
    show += "</section>"
HERO_CSS = """
.gs-note{margin:22px 0 0;font-size:15.5px;line-height:1.5;color:var(--muted)} .gs-note a{color:var(--accent);font-weight:600}
.home.has-vid .in{grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-areas:"eb vid" "h1 vid" "tl vid" "try vid" ". vid";grid-template-rows:auto auto auto auto 1fr;align-items:start;align-content:start;column-gap:48px;row-gap:22px;padding-block:36px 40px}
.home.has-vid .eyebrow{grid-area:eb} .home.has-vid h1{grid-area:h1;font-size:clamp(44px,5vw,72px);margin:0}
.home.has-vid .tagline{grid-area:tl;font-size:clamp(19px,1.8vw,23px);margin:0} .home.has-vid .tries{grid-area:try;margin-top:6px}
.hero-vid{grid-area:vid;margin:0;display:grid;gap:10px;align-self:start;justify-self:end;width:100%;max-width:560px;min-width:0}
.hero-vid figcaption{font-size:15px;color:var(--muted);line-height:1.45}
.hero-vid figcaption b{color:var(--fg)}
.vid{position:relative;aspect-ratio:1/1;width:100%;overflow:hidden;border-radius:12px;border:1px solid var(--line);background:var(--card);box-shadow:0 1px 0 var(--line)}
.vid-play{position:absolute;inset:0;width:100%;height:100%;padding:0;border:0;background:none;cursor:pointer;display:block}
.vid-play picture,.vid-play img{display:block;width:100%;height:100%;object-fit:cover}
.vid-knob{position:absolute;top:50%;left:50%;width:84px;height:84px;margin:-42px 0 0 -42px;border-radius:50%;background:var(--accent);color:#fff;
  display:grid;place-items:center;box-shadow:0 4px 18px rgba(0,0,0,.35);transition:transform .15s ease}
.vid-knob svg{margin-left:4px}
.vid-play:hover .vid-knob{transform:scale(1.07)}
.vid-play:focus-visible{outline:none} .vid-play:focus-visible .vid-knob{box-shadow:0 0 0 4px #fff,0 0 0 7px var(--accent)}
.vid iframe{position:absolute;inset:0;width:100%;height:100%;border:0;display:block}
.pp{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,7fr);gap:28px;align-items:center;margin:28px 0;padding:22px;background:var(--card);border:1px solid var(--line);border-radius:14px}
.pp-txt{display:grid;gap:8px;align-content:start}
.pp h2{font:400 40px/1.05 "Instrument Serif",Georgia,serif;margin:0;text-wrap:balance}
.pp .sub{margin:0;font-size:18px;color:var(--muted);line-height:1.4}
@media (max-width:960px){
 .home.has-vid .in{grid-template-columns:minmax(0,1fr);grid-template-areas:"eb" "h1" "vid" "tl" "try";grid-template-rows:none;padding-block:24px 32px}
 .home.has-vid h1{font-size:clamp(40px,10.5vw,64px)}
 .hero-vid{justify-self:center}
 .pp{grid-template-columns:minmax(0,1fr);padding:14px;gap:16px}
}
@media (max-width:440px){.vid-knob{width:68px;height:68px;margin:-34px 0 0 -34px}}
"""
# Click-to-play: swap the cover button for the iframe. Until then the page makes no request to YouTube.
VID_JS = r"""
<script>
[].forEach.call(document.querySelectorAll('[data-yt]'),function(v){
  var b=v.querySelector('.vid-play'); if(!b) return;
  b.addEventListener('click',function(){
    var f=document.createElement('iframe');
    f.src='https://www.youtube-nocookie.com/embed/'+v.getAttribute('data-yt')+'?autoplay=1&rel=0&playsinline=1';
    f.title='Proofs at work, one minute';
    f.allow='autoplay; encrypted-media; picture-in-picture; fullscreen'; f.setAttribute('allowfullscreen','');
    v.replaceChild(f,b); f.focus();
  });
});
</script>"""
body = f'''<header class="top"><div class="in"><a class="logo" href="index.html">pro<i>o</i>fs</a><span>/ skills for Claude Code</span>{"<a href=\"#examples\" style=\"margin-left:auto;text-decoration:none\">Examples</a><a href=\"#skills\" style=\"text-decoration:none\">Skills ↓</a>" if (feat or steps) else "<a href=\"#skills\" style=\"margin-left:auto;text-decoration:none\">All skills ↓</a>"}<a href="https://github.com/workingBen/proofs" style="text-decoration:none">GitHub ↗</a></div></header>
<section class="hero home has-vid"><div class="in">
  <div class="eyebrow">Skills for Claude Code · {len([s for _, g in GROUPS for s in g])} skills · {total_f}+ features</div>
  <h1>Claude skills that <i>show</i> their work.</h1>{hero_vid}
  <p class="tagline">Stop reading walls of terminal text. Every skill here includes a page you can look at, click through and decide on, then hand back to Claude in one paste.</p>
  <div class="tries"><div class="try"><span class="lbl">Install in Claude Code</span><div class="trybox"><code>/plugin marketplace add workingBen/proofs
/plugin install proofs@proofs</code><button type="button" class="tryb">Copy</button></div></div>
  <div class="try"><span class="lbl">Then try this prompt</span><div class="trybox wrap"><code>Use the design-review skill to propose two or three design updates for the page [YOUR URL]</code><button type="button" class="tryb">Copy</button></div></div></div>
</div></section>
{show}<section class="loopw"><div class="in"><h2 class="h2">How every skill works</h2><div class="loop">
  <div class="step"><span class="n">01</span><b>Claude shows you first</b><span>Mockups, measurements and drafts, before anything changes.</span></div>
  <div class="step"><span class="n">02</span><b>Publishes a page</b><span>A private review page, not a wall of chat.</span></div>
  <div class="step you"><span class="n">03</span><b>You decide visually</b><span>Clear buttons on every item, and room for a comment. Works on a phone.</span></div>
  <div class="step"><span class="n">04</span><b>Paste it back</b><span>One Copy button. Claude does exactly what you chose.</span></div>
</div></div></section>
<section class="in" id="skills" style="padding-block:24px 80px"><h2 class="h2">All skills</h2>{cards}</section>
<footer class="foot"><div class="in"><span>proofs · Claude skills that show their work</span><span><a href="https://github.com/workingBen/proofs">Code on GitHub</a> · MIT license</span></div></footer>
<script>
/* Copy buttons. If the clipboard is blocked, select the text so a long-press copies it;
   never say "Copied" unless it was. */
[].forEach.call(document.querySelectorAll('.tryb'),function(b){{var c=b.previousElementSibling;
b.addEventListener('click',function(){{function pick(){{var r=document.createRange();r.selectNodeContents(c);var g=getSelection();g.removeAllRanges();g.addRange(r)}}
if(!navigator.clipboard||!navigator.clipboard.writeText)return pick();
navigator.clipboard.writeText(c.textContent).then(function(){{b.textContent='Copied';setTimeout(function(){{b.textContent='Copy'}},1500)}},pick)}})}});
</script>''' + VID_JS + (showcase.JS if exs else '')
extra = '''
.home h1{font-size:clamp(44px,8vw,92px)} .home h1 i{color:var(--accent)}
.home .trybox code{white-space:pre;overflow-x:auto}
.home .try{max-width:100%;min-width:0}
.home .trybox.wrap code{white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:visible}
.tries{display:grid;gap:16px;min-width:0}
.home .in{min-width:0}
.h2{font:400 40px/1.1 "Instrument Serif",Georgia,serif;margin:0 0 18px}
.loopw .in{padding-block:8px 32px}
.loop{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.step{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;display:grid;gap:4px}
.step.you{background:var(--accent-soft);border-color:var(--accent)}
.step .n{font:600 12px "JetBrains Mono",monospace;color:var(--accent)}
.step b{font-size:17px} .step span{font-size:14.5px;color:var(--muted)}
.grp{margin-bottom:36px}
.grp h3{display:flex;gap:10px;align-items:baseline;font:650 20px/1.3 -apple-system,sans-serif;margin:0 0 12px}
.grp h3 span{font:600 12px "JetBrains Mono",monospace;color:var(--accent)}
.sk-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
@media (min-width:760px){.sk-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.sk-card{display:grid;gap:8px;align-content:start;text-decoration:none;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;transition:border-color .15s}
a.sk-card:hover{border-color:var(--accent)}
.sk-card.wait{opacity:.6}
.sk-top{display:flex;gap:8px;align-items:baseline;justify-content:space-between}
.sk-top b{font:400 28px/1.1 "Instrument Serif",Georgia,serif}
.sk-top em{font:600 11px "JetBrains Mono",monospace;font-style:normal;color:var(--accent);white-space:nowrap}
.sk-tag{margin:0;font-size:15.5px}
.sk-chips{display:flex;flex-wrap:wrap;gap:5px}
.sk-chips span{font:600 11.5px -apple-system,sans-serif;padding:4px 9px;border-radius:999px;background:var(--soft);color:var(--muted)}
.sk-chips .more{background:none;border:1px dashed var(--line)}
.sk-card{position:relative}
.sk-grid{padding-top:10px}
.sk-pic{display:block;width:100%;height:auto;aspect-ratio:2.6/1;object-fit:cover;border-radius:9px;border:1px solid var(--line);margin-top:4px}
.sk-pick,.sk-ribbon{position:absolute;top:-12px;display:inline-flex;align-items:center;gap:5px;font:700 11px/1 "JetBrains Mono",monospace;letter-spacing:.08em;text-transform:uppercase;padding:6px 10px;border-radius:999px}
.sk-pick{left:16px;background:var(--card);color:var(--accent);border:1px solid var(--accent)}
.sk-ribbon{right:16px;background:var(--accent);color:#fff}
@media (max-width:800px){.loop{grid-template-columns:1fr 1fr}}
@media (max-width:440px){.loop{grid-template-columns:1fr}.sk-grid{grid-template-columns:1fr}.top .in>span{display:none}
 .home .trybox{flex-wrap:wrap;padding:12px}.home .trybox code{flex-basis:100%;font-size:12.5px;white-space:pre-wrap;overflow-wrap:anywhere;overflow-x:visible}.home .trybox button{width:100%}}
'''
HEAD = '<!doctype html>\n<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
out = HEAD + links + "<style>" + style + extra + HERO_CSS + (showcase.CSS if exs else "") + "</style>\n" + body
OUT = showcase.out_dir()
os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.join(OUT, "media"), exist_ok=True)
for f in ("proofs-short-cover.jpg", "proofs-short-cover.webp"):
    shutil.copyfile(os.path.join(MEDIA, f), os.path.join(OUT, "media", f))
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(out)
print("index:", n_sk, "skill pages,", total_f, "features")
