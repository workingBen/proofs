// The Proofs card picture (1200x630): the link preview for the website and the repo.
// See BRAND.md ("Card pictures"). The published copy is docs/assets/social-card.jpg.
//
// Run (needs Node and Playwright; Chrome is used as the browser):
//   node assets/card/render.cjs [out.png]
//     or, with Playwright installed somewhere else:
//   PLAYWRIGHT=~/.cache/proofs-playwright/node_modules/playwright node assets/card/render.cjs
// Then convert for the site (macOS):
//   sips -s format jpeg -s formatOptions 85 proofs-card.png --out site-src/media/social-card.jpg
//   python3 site-src/build.py
//
// Every Chrome launch passes --disable-features=MacAppCodeSignClone; without it macOS
// leaves a full copy of Chrome behind in a temp folder on every run.
const { chromium } = require(process.env.PLAYWRIGHT || 'playwright');
const path = require('path');

const FONT = '<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800;900&family=JetBrains+Mono:wght@500;600&display=block" rel="stylesheet">';

const CSS = `
*{box-sizing:border-box;margin:0;padding:0}
body{width:1200px;height:630px;overflow:hidden}
.og{position:relative;width:1200px;height:630px;overflow:hidden;font-family:Inter,"SF Pro Display",-apple-system,system-ui,sans-serif;color:#efe8dc;
  background:radial-gradient(110% 130% at 88% 0%,#2f2719 0%,#231e15 42%,#18150f 75%,#121009 100%)}
.txt{position:absolute;left:84px;top:0;bottom:0;width:600px;display:flex;flex-direction:column;justify-content:center}
.panel{position:absolute;left:720px;top:48px;width:420px;height:640px;border-radius:34px;background:#faf8f2;box-shadow:0 30px 80px rgba(0,0,0,.35);padding:34px 32px;color:#1f2a24}
.bar{height:22px;border-radius:11px;background:#e7e1d5;margin-bottom:16px}
.chip{position:absolute;border-radius:20px;padding:24px 30px 26px;box-shadow:0 18px 40px rgba(0,0,0,.28)}
.chip i{display:block;font-style:normal;font-family:"JetBrains Mono",ui-monospace,Menlo,monospace;font-size:19px;letter-spacing:.14em;opacity:.78;margin-bottom:16px}
.chip b{display:block;font-weight:700;font-size:33px;line-height:1.15;letter-spacing:-.01em}
.cream{background:#f8f5ee;color:#1f2a24;transform:rotate(3deg)}
.orange{background:#ff8a4c;color:#1b130c;transform:rotate(-4deg)}
/* variant tiles */
.vrow{display:flex;gap:16px;margin:8px 0 24px}
.vt{flex:1;height:200px;border-radius:18px;background:#f0ebe1;padding:14px;position:relative;border:4px solid transparent}
.vt .l{font-family:"JetBrains Mono",monospace;font-weight:600;font-size:18px;color:#7a7468;margin-bottom:10px}
.vt .g{height:70px;border-radius:12px;background:linear-gradient(135deg,#9fd0b6,#d7ebdf);margin-bottom:12px}
.vt .s{height:12px;border-radius:6px;background:#ddd5c6;margin-bottom:9px}
.vt.on{border-color:#c2410c;background:#fff}
.vt.on .ck{position:absolute;top:-16px;right:-14px;width:44px;height:44px;border-radius:50%;background:#c2410c;color:#fff;font-weight:900;font-size:26px;display:flex;align-items:center;justify-content:center}
.btn{height:64px;border-radius:999px;background:#c2410c;margin-top:10px;width:250px}
/* wordmark */
.wm{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:150px;letter-spacing:-.02em;line-height:.9}
.wm i{color:#ff8a4c}
.ser{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:48px;line-height:1.18;letter-spacing:0}
.ser i{color:#ff8a4c}
.kick{font-family:"JetBrains Mono",monospace;font-weight:600;font-size:20px;letter-spacing:.16em;color:#a69d8e;margin-bottom:26px;display:flex;align-items:center;gap:14px}
.kick::before{content:"";width:16px;height:16px;border-radius:4px;background:#ff8a4c}
`;

const CARD = `<div class="og">
    <div class="txt"><div class="kick">SKILLS FOR CLAUDE CODE</div><div class="wm">pro<i>o</i>fs</div><div class="ser" style="margin-top:30px">Claude Code skills<br>that <i>show</i> their work.</div></div>
    <div class="panel"><div class="bar" style="width:55%"></div>
      <div class="vrow"><div class="vt"><div class="l">A</div><div class="g"></div><div class="s"></div><div class="s" style="width:70%"></div></div>
        <div class="vt on"><span class="ck">✓</span><div class="l">B</div><div class="g"></div><div class="s"></div><div class="s" style="width:60%"></div></div></div>
      <div class="bar" style="width:80%"></div><div class="bar" style="width:62%"></div><div class="btn"></div></div>
    <div class="chip orange" style="left:640px;top:272px;width:300px"><i>PICK 1</i><b>Variant B</b></div>
    <div class="chip cream" style="left:835px;top:452px;width:325px"><i>NOTE 2</i><b>Make the button<br>lighter orange</b></div>
  </div>`;

(async () => {
  const out = path.resolve(process.argv[2] || path.join(__dirname, 'proofs-card.png'));
  const browser = await chromium.launch({ channel: 'chrome', args: ['--disable-features=MacAppCodeSignClone'] });
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  await page.setContent(`<!doctype html><html><head>${FONT}<style>${CSS}</style></head><body>${CARD}</body></html>`, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: out, clip: { x: 0, y: 0, width: 1200, height: 630 } });
  console.log('wrote', out);
  await browser.close();
})();
