import html, json, os, sys
import showcase
e = html.escape
HERE = os.path.dirname(os.path.abspath(__file__))
skill = sys.argv[1] if len(sys.argv) > 1 else "design-review"
d = json.load(open(os.path.join(HERE, "pages", f"{skill}.json")))

def SK(w="100%", h=7, dark=False): return f'<i class="mk{" d" if dark else ""}" style="width:{w};height:{h}px"></i>'
def B(t, on=False, cls=""): return f'<span class="mb{" on" if on else ""} {cls}">{t}</span>'
def page(*rows, cls=""): return f'<div class="pg {cls}">{"".join(rows)}</div>'
LAY = lambda: SK("90%", 18, True) + SK("70%") + SK("50%")
CHECK = '<svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 8.5l3.2 3L13 4.5"/></svg>'

ILL = {} if skill != "design-review" else {
 "f1": f'<div class="win"><div class="wb"><i></i><i></i><i></i><span>Before · your live page</span></div><div class="wbody">{SK("100%",26,True)}<div class="two">{SK("100%",30)}{SK("100%",30)}</div>{SK("70%")}</div><span class="cam"><svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M2 5h3l1.2-1.5h3.6L11 5h3v8H2z"/><circle cx="8" cy="9" r="2.3"/></svg> real screenshot</span></div>',
 "f2": '<div class="three">' + "".join(f'<div class="opt"><span class="tag">{l}</span>{x}</div>' for l, x in [("A", SK("100%",22,True)+SK()+SK("60%")), ("B", '<div class="two">'+SK("100%",28,True)+'<div class="col">'+SK()+SK("60%")+'</div></div>'+SK()), ("C", SK("50%")+SK("100%",32,True))]) + '</div>',
 "f3": f'<div class="two mid"><div class="col"><div class="sw"><b style="background:#c2410c"></b><b style="background:#1d1b17"></b><b style="background:#e9e1d1"></b><b style="background:#1a7f37"></b></div><div class="aa">Aa <small>your fonts</small></div></div><div class="opt brand"><span class="tag">Mockup</span><i class="mk" style="height:20px;background:#c2410c"></i>{SK()}{SK("60%")}</div></div>',
 "f4": f'<div class="two mid"><div class="opt"><span class="tag">Live</span><div class="hl">Spring hours</div>{SK()}</div><div class="opt"><span class="tag">Local</span><div class="hl strike">Lorem title</div><div class="hl ok">Spring hours {CHECK}</div></div></div>',
 "f5": '<div class="pg">' + "".join(f'<div class="band"><span class="num">{n}</span>{SK("80%", h, n==1)}</div>' for n, h in [(1, 18), (2, 10), (3, 10)]) + '</div>',
 "f6": f'<div class="col"><div class="row"><b class="hd">Header</b><span class="rec yes">Recommended</span></div><div class="row"><b class="hd">Footer</b><span class="rec no">Not recommended</span></div><div class="why"><b>Reason:</b> larger type reads better on phones.</div></div>',
 "f7": f'<div class="two mid"><div class="phone">{SK("100%",16,True)}{SK()}{SK("70%")}{SK()}</div><div class="desk"><div class="two">{SK("100%",30,True)}<div class="col">{SK()}{SK("60%")}{SK("80%")}</div></div></div></div>',
 "f8": f'<div class="col"><div class="openi"><span class="dot"></span>Open · Header</div><div class="openi"><span class="dot"></span>Open · Card grid</div><div class="recap">Recap · 3 settled ▸</div></div>',
 "f9": '<div class="three">' + f'<div class="opt"><span class="tag">A</span>{LAY()}</div><div class="opt sel"><span class="tag">B</span><span class="ck">{CHECK}</span>{LAY()}</div><div class="opt"><span class="tag">C</span>{LAY()}</div>' + '</div>',
 "f10": f'<div class="row wrap">{B("Keep Original")}{B("Use Selected", True)}{B("Approve with Comment")}{B("Request Revision")}</div>',
 "f11": f'<div class="col"><div class="opt">{LAY()}</div><div class="row">{B("Keep Original")}{B("Use Proposed", True)}</div></div>',
 "f12": f'<div class="col"><div class="row">{B("Request Revision", True)}</div><div class="cbox">try less white space<span class="caret"></span></div></div>',
 "f13": '<div class="col">' + "".join(f'<div class="row"><b class="hd">{t}</b><span class="pill {c}">{p}</span></div>' for t, p, c in [("1 · Header", "Accepted", "ok"), ("2 · Cards", "Revise", "mid"), ("3 · Footer", "Kept", "mute"), ("4 · Nav", "Pending", "line")]) + '</div>',
 "f14": f'<div class="col"><div class="itm"><span>2 · Cards</span><span class="tg on"><b></b></span><small>Read</small></div><div class="itm"><span>3 · Footer</span><span class="tg"><b></b></span><small>Read</small></div><div class="note2">Next round: read items drop out</div></div>',
 "f15": '<div class="bottom"><span>3 of 5 reviewed</span><span class="tally"><b class="ok">2</b><b class="mid">1</b><b class="mute">0</b></span><span class="mb on sm">Copy</span></div>',
 "f16": f'<div class="col"><div class="row">{B("Copy My Decisions", True, "acc")}</div><pre class="ex">[Articles index · Design review]\n1. Card layout: ACCEPT (Variant B)\n2. Header: REVISE: "less white space"</pre></div>',
 "f17": '<div class="col">' + "".join(f'<div class="row flow"><span class="st {c}">{t}</span><span class="arr">{a}</span></div>' for t, c, a in [("1 · Accepted", "ok", "→ built"), ("2 · Revise", "mid", "untouched"), ("3 · Accepted", "ok", "→ built"), ("4 · Kept", "mute", "untouched")]) + '</div>',
 "f18": f'<div class="two mid"><div class="opt"><span class="tag">Mockup</span>{SK("100%",14,True)}<div class="ph">Sample title</div></div><div class="code"><span class="tag" style="color:inherit;opacity:.7">your template</span><span>for post in posts:</span><span>&nbsp;&nbsp;card(post)</span></div></div>',
 "f19": f'<div class="two mid"><div class="opt">{SK("100%",18,True)}{SK()}<div class="row">{B("Use")}{B("Keep")}</div></div><div class="col chk"><span>{CHECK} buttons work</span><span>{CHECK} export correct</span><span>{CHECK} no sideways scroll</span></div></div>',
 "f20": f'<div class="two mid"><div class="col"><span class="tag">Round 1 · 5 items</span>{SK()}{SK()}{SK()}{SK()}{SK()}</div><div class="col"><span class="tag acc">Round 2 · 1 item</span>{SK("100%",7,True)}<span class="link">same link</span></div></div>',
 "f21": f'<div class="three"><div class="opt old"><span class="tag">Round 1</span>{LAY()}</div><div class="opt"><span class="tag acc">Round 2 · A</span>{LAY()}</div><div class="opt"><span class="tag acc">Round 2 · B</span>{LAY()}</div></div>',
 "f22": '<div class="col"><div class="bub">not sure, show me a few</div><div class="four">' + "".join(f'<div class="opt sm"><span class="tag">{l}</span>{SK("100%", 10 + 6*i, True)}</div>' for i, l in enumerate("ABCD")) + '</div></div>',
}

secs, toc = "", ""
n = 0
for si, s in enumerate(d["sections"]):
    sid = f"s{si+1}"
    toc += f'<li><a href="#{sid}">{e(s["title"])}</a><ol>'
    rows = ""
    for f in s["features"]:
        n += 1
        toc += f'<li><a href="#{f["id"]}">{e(f.get("label", f["title"]))}</a></li>'
        rows += f'''<article class="feat" id="{f["id"]}"><div class="fx"><span class="fn">{n:02d}</span><h3>{e(f.get("label", f["title"]))}</h3><p class="sub">{e(f.get("sub", ""))}</p><p>{e(f["what"])}</p></div><div class="fig" aria-hidden="true">{f.get("html") or ILL.get(f["id"], "")}</div></article>'''
    toc += "</ol></li>"
    secs += f'<section class="sec" id="{sid}"><h2><span>{si+1}</span>{e(s["title"])}</h2>{rows}</section>'

tpl = open(os.path.join(HERE, "skillpage_tpl.html")).read()
out = (tpl.replace("%%SKILL%%", e(skill)).replace("%%TAGLINE%%", e(d["tagline"])).replace("%%USE%%", e(d["use_when"]))
          .replace("%%TRY%%", e(d["try_it"])).replace("%%TOC%%", toc).replace("%%SECS%%", secs).replace("%%N%%", str(n)).replace("%%PROMISE%%", "".join(f"<span>{e(x)}</span>" for x in d.get("promises", []))))
from site_order import ORDER
pn = ""
if skill in ORDER:
    i = ORDER.index(skill)
    pv, nx = ORDER[i-1] if i > 0 else None, ORDER[i+1] if i+1 < len(ORDER) else None
    pn = '<nav class="pn" aria-label="More skills"><div class="in">' + (f'<a href="{pv}.html"><span>Previous</span><b>{pv}</b></a>' if pv else '<i></i>') + (f'<a class="nx" href="{nx}.html"><span>Next</span><b>{nx}</b></a>' if nx else '') + '</div></nav>'
out = out.replace("%%PREVNEXT%%", pn)
mine = [x for x in showcase.load() if x["skill"] == skill]
exs = ""
if mine:
    exs = ('<section class="in showcase" id="examples"><div class="lede"><div class="eyebrow">Real work, before and after</div>'
           f'<h2>See it work</h2><p>Real pages, before and after a {e(skill)} round. '
           'They play on their own. Drag a slider to compare.</p></div>' + showcase.gallery(mine, link=False) + '</section>')
out = (out.replace("%%EXAMPLES%%", exs).replace("%%EXCSS%%", showcase.CSS if mine else "")
          .replace("%%EXJS%%", showcase.JS.lstrip("\n") if mine else ""))
OUT = showcase.out_dir()
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, f"{skill}.html"), "w", encoding="utf-8").write('<!doctype html>\n<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n' + out)
print(skill, n, "features")
