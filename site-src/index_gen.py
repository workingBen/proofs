import html, json, os, re
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
<p class="sk-tag">{e(d["tagline"])}</p><div class="sk-chips">{chips}<span class="more">+{max(0, len(feats)-4)} more</span></div>{pic}</a>'''
    cards += f'<section class="grp"><h3><span>{gi+1:02d}</span>{e(gname)}</h3><div class="sk-grid">{items}</div></section>'

exs = showcase.load()
hero = next((x for x in exs if x["use"] == "hero" and len(x["frames"]) == 2), None)
steps = next((x for x in exs if x["use"] == "hero" and len(x["frames"]) > 2), None)
feat = [x for x in exs if x["use"] == "featured"]
hero_ba = ""
if hero:
    hero_ba = (f'<figure class="hero-ba">{showcase.slider(hero, big=True, eager=True)}'
               f'<figcaption><b>{e(hero["title"])}.</b> {e(hero["caption"])} '
               f'<a href="{e(hero["skill"])}.html">{e(hero["skill"])}</a></figcaption></figure>')
show = ""
if feat or steps:
    # Every example except the one in the top slider, in ORDER, so the best come first.
    items = [x for x in exs if x is not hero and x["use"] != "skill"]
    show = ('<section class="in showcase" id="examples"><div class="lede"><div class="eyebrow">Real work, before and after</div>'
            '<h2>See it work</h2><p>Each pair is a real page before and after one review. They slide on their own. Drag any of them.</p></div>'
            + showcase.gallery(items))
    show += "</section>"
HERO_CSS = """
.home.has-ba .in{grid-template-columns:minmax(0,5fr) minmax(0,7fr);grid-template-areas:"eb ba" "h1 ba" "tl ba" "ch ba" "try ba";align-items:start;column-gap:44px;row-gap:14px;padding-block:36px 40px}
.home.has-ba .eyebrow{grid-area:eb} .home.has-ba h1{grid-area:h1;font-size:clamp(44px,5.2vw,76px)}
.home.has-ba .tagline{grid-area:tl;font-size:clamp(20px,2.1vw,26px)} .home.has-ba .chipset{grid-area:ch} .home.has-ba .try{grid-area:try}
.hero-ba{grid-area:ba;margin:0;display:grid;gap:10px;align-self:center;min-width:0}
.hero-ba figcaption{font-size:15px;color:var(--muted);line-height:1.45}
.hero-ba figcaption b{color:var(--fg)} .hero-ba figcaption a{color:var(--accent);font:600 13px "JetBrains Mono",monospace}
.pp{display:grid;grid-template-columns:minmax(0,4fr) minmax(0,7fr);gap:28px;align-items:center;margin:28px 0;padding:22px;background:var(--card);border:1px solid var(--line);border-radius:14px}
.pp-txt{display:grid;gap:8px;align-content:start}
.pp h2{font:400 40px/1.05 "Instrument Serif",Georgia,serif;margin:0;text-wrap:balance}
.pp .sub{margin:0;font-size:18px;color:var(--muted);line-height:1.4}
@media (max-width:960px){
 .home.has-ba .in{grid-template-columns:minmax(0,1fr);grid-template-areas:"eb" "h1" "ba" "tl" "ch" "try";padding-block:24px 32px}
 .home.has-ba h1{font-size:clamp(40px,10.5vw,64px)}
 .pp{grid-template-columns:minmax(0,1fr);padding:14px;gap:16px}
}
"""
body = f'''<header class="top"><div class="in"><a class="logo" href="index.html">pro<i>o</i>fs</a><span>/ skills for Claude Code</span>{"<a href=\"#examples\" style=\"margin-left:auto;text-decoration:none\">Examples</a><a href=\"#skills\" style=\"text-decoration:none\">Skills ↓</a>" if (feat or steps) else "<a href=\"#skills\" style=\"margin-left:auto;text-decoration:none\">All skills ↓</a>"}</div></header>
<section class="hero home{" has-ba" if hero else ""}"><div class="in">
  <div class="eyebrow">Skills for Claude Code · {len([s for _, g in GROUPS for s in g])} skills · {total_f}+ features</div>
  <h1>Claude skills that <i>show</i> their work.</h1>{hero_ba}
  <p class="tagline">Stop reading walls of terminal text. Every skill here includes a page you can look at, click through and decide on, then hand back to Claude in one paste.</p>
  <div class="chipset"><span class="dchip">Keep original</span><span class="dchip on">Use selected</span><span class="dchip">Approve with comment</span><span class="dchip">Request revision</span></div>
  <div class="try"><span class="lbl">Install in Claude Code</span><div class="trybox"><code id="tryc">/plugin marketplace add workingBen/proofs
/plugin install proofs@proofs</code><button type="button" id="tryb">Copy</button></div></div>
</div></section>
{show}<section class="loopw"><div class="in"><h2 class="h2">How every skill works</h2><div class="loop">
  <div class="step"><span class="n">01</span><b>Claude shows you first</b><span>Mockups, measurements and drafts, before anything changes.</span></div>
  <div class="step"><span class="n">02</span><b>Publishes a page</b><span>A private review page, not a wall of chat.</span></div>
  <div class="step you"><span class="n">03</span><b>You decide visually</b><span>Clear buttons on every item, and room for a comment. Works on a phone.</span></div>
  <div class="step"><span class="n">04</span><b>Paste it back</b><span>One Copy button. Claude does exactly what you chose.</span></div>
</div></div></section>
<section class="in" id="skills" style="padding-block:24px 80px"><h2 class="h2">All skills</h2>{cards}</section>
<footer class="foot"><div class="in"><span>proofs · Claude skills that show their work</span><span>MIT license</span></div></footer>
<script>
(function(){{var b=document.getElementById('tryb'),c=document.getElementById('tryc');
b.addEventListener('click',function(){{try{{navigator.clipboard.writeText(c.textContent).then(function(){{b.textContent='Copied';setTimeout(function(){{b.textContent='Copy'}},1500)}},function(){{}})}}catch(_){{}}}});}})();
</script>''' + (showcase.JS if exs else '')
extra = '''
.home h1{font-size:clamp(44px,8vw,92px)} .home h1 i{color:var(--accent)}
.home .trybox code{white-space:pre;overflow-x:auto}
.home .try{max-width:100%;min-width:0}
.home .in{min-width:0}
.chipset{display:flex;gap:6px;flex-wrap:wrap}
.dchip{font:600 12px/1 "JetBrains Mono",monospace;padding:8px 11px;border-radius:999px;border:1.5px solid var(--fg)}
.dchip.on{background:var(--fg);color:var(--bg)}
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
.sk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
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
out = HEAD + links + "<style>" + style + extra + (showcase.CSS + HERO_CSS if exs else "") + "</style>\n" + body
OUT = showcase.out_dir()
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(out)
print("index:", n_sk, "skill pages,", total_f, "features")
