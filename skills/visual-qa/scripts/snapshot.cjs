// Snapshot: a standalone copy of the page as rendered, the "base" design-review's Refine mode
// builds on (spec §2). capture.cjs --snapshot calls it on each page right after the 1280 shot, so
// the page has been through the capture's scroll-through (reveal-on-scroll sections and lazy
// images are there) and is back at the top.
//
//   const { snapshotPage } = require('./snapshot.cjs');
//   await snapshotPage(page, outDir, name)
//     -> { file, assets, bytes, canvases, external }
//
// Writes <outDir>/<name>-snapshot.html and <outDir>/<name>-snapshot-assets/*:
//   - the DOM as it is now (document.documentElement, so content scripts added is kept), with
//     its doctype, so a page in quirks mode stays in quirks mode;
//   - every readable stylesheet (linked, <style>, @import, rules a script inserted) inlined as a
//     <style> from its cssRules, in place, so the cascade order and the page's own media queries
//     are unchanged (a 390 frame shows the phone layout);
//   - a stylesheet from another origin cannot be read in the page (cssRules throws), so its text
//     is fetched node-side with the page's cookies (as assets are), its url()s resolved against
//     its own URL and fetched into the assets folder, its @imports followed, and it is inlined in
//     the same place: a published page loads no stylesheet from another site but Google Fonts.
//     One that cannot be fetched stays an @import of its absolute URL and is listed in
//     `external` (dropping it would silently lose its rules);
//   - each url() in CSS and style attributes, and each img/source src and srcset, video poster
//     and svg <image> target, fetched with the page's own cookies into the assets folder and
//     referenced by a plain relative path ("<name>-snapshot-assets/<hash>-<file>"), no <base>.
//     A target that cannot be fetched keeps its absolute URL;
//   - each <canvas> drawn into a PNG in the assets folder and swapped for an <img> with the
//     canvas's attributes, width and height (`canvases` counts them; a canvas tainted by a
//     cross-origin image cannot be read and stays an empty canvas). Inline SVG is kept as is; an
//     svg <use> of another file gets the element it names copied in (see below);
//   - no <script>, <noscript>, on* attribute or javascript: URL, no <base>, no meta refresh or
//     CSP (an inline-style CSP would block the inlined sheets), and a single <meta charset=utf-8>;
//   - typed form values written back into the markup; other links made absolute, with no
//     `target` (a tap must not navigate the review page); hidden inputs blanked and the
//     csrf-token and csrf-param metas dropped, so no session token is published;
//   - no srcdoc on a nested <iframe>: its HTML never went through the stripping above.
// `assets` lists the files written, relative to outDir; `bytes` is the page plus its assets.
// Not kept: open or closed shadow roots (web components render empty), blob: URLs, and CSS
// properties Chrome drops when it parses a sheet (another engine's prefixes).

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { fileURLToPath } = require('url');

// Runs in the page. Returns the serialized copy with tokens where asset paths go, and the URLs.
async function collectSnapshot() {
  const urls = [];
  const seen = new Map();
  // Sheets this page cannot read (another origin, so cssRules throws): each leaves a
  // __PROOFS_SHEET_<i>__ token where its rules go, and snapshotPage fetches its text node-side.
  const sheets = [];
  const sheetToken = (href, media) => { sheets.push({ href, media: media || '' }); return `__PROOFS_SHEET_${sheets.length - 1}__`; };
  const base = document.baseURI;
  const resolve = (u, from) => { try { return new URL(u, from).href; } catch (_) { return null; } };
  // ctx 'a': the token lands in an attribute; 's': in a <style> element's text. Each URL carries
  // the document that named it (`from`: the page, a sheet, a fetched sprite), which decides
  // whether a file: URL may be read (snapshotPage, fileAllowed). One URL named from more than one
  // place keeps a non-file referrer when it has one, so it is never read on another's behalf.
  const token = (abs, ctx, from) => {
    const hash = abs.indexOf('#');
    const bare = hash >= 0 ? abs.slice(0, hash) : abs;
    if (!seen.has(bare)) { seen.set(bare, urls.length); urls.push({ url: bare, from }); }
    else if (!/^file:/i.test(from || '')) urls[seen.get(bare)].from = from;
    return `__PROOFS_ASSET_${ctx}_${seen.get(bare)}__${hash >= 0 ? abs.slice(hash) : ''}`;
  };
  const asset = (u, from, ctx) => {
    if (!u || /^(data|blob|about|javascript):/i.test(u.trim()) || u.trim().startsWith('#')) return null;
    const abs = resolve(u.trim(), from);
    return abs && /^(https?|file):/i.test(abs) ? token(abs, ctx, from) : null;
  };
  const rewriteCss = (text, from, ctx) => text.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi,
    (m, q, u) => { const t = asset(u, from, ctx); return t ? `url("${t}")` : m; });

  // A sheet's rules as text, @imports inlined where readable. Returns null when the sheet itself
  // cannot be read. Kept @imports (cross-origin) are hoisted, since @import must come first.
  const sheetText = (sheet, from, imports) => {
    let rules;
    try { rules = sheet.cssRules; } catch (_) { return null; }
    if (!rules) return null;
    const out = [];
    for (const r of rules) {
      if (r.type === CSSRule.IMPORT_RULE) {
        // Only the import's media is carried; its layer(...) and supports(...) are not (a known gap).
        const media = r.media && r.media.mediaText;
        if (!r.styleSheet) continue; // it never loaded, so it never applied
        const href = r.styleSheet.href || resolve(r.href, from);
        const inner = sheetText(r.styleSheet, href, imports);
        if (inner == null) imports.push(sheetToken(href, media));
        else out.push(media ? `@media ${media} {\n${inner}\n}` : inner);
      } else out.push(rewriteCss(r.cssText, from, 's'));
    }
    return out.join('\n');
  };

  const live = document.documentElement;
  const liveAll = [...live.querySelectorAll('*')];
  const clone = live.cloneNode(true);
  const cloneAll = [...clone.querySelectorAll('*')];
  const twin = (el) => cloneAll[liveAll.indexOf(el)];

  // Stylesheets, in place.
  for (const sheet of [...document.styleSheets]) {
    const owner = sheet.ownerNode;
    const el = owner && owner.nodeType === 1 ? twin(owner) : null;
    if (!el) continue;
    if (sheet.disabled) { el.remove(); continue; }
    const imports = [];
    const from = sheet.href || base;
    const text = sheetText(sheet, from, imports);
    const style = document.createElement('style');
    if (text == null) {
      // Its rules go here once fetched; the sheet's media stays on the <style>, as below.
      if (el.tagName !== 'LINK' || !owner.href) continue;
      if (sheet.media && sheet.media.mediaText) style.setAttribute('media', sheet.media.mediaText);
      style.textContent = sheetToken(owner.href, '');
      el.replaceWith(style);
      continue;
    }
    // The sheet's MediaList, not owner.media: on <link> and <style> that is a plain string, so
    // .mediaText was always undefined and a print or max-width sheet applied everywhere.
    if (sheet.media && sheet.media.mediaText) style.setAttribute('media', sheet.media.mediaText);
    style.textContent = [...imports, text].join('\n');
    el.replaceWith(style);
  }
  // Sheets a script built (adoptedStyleSheets) come after the document's own, as they apply.
  for (const sheet of document.adoptedStyleSheets || []) {
    const imports = [];
    const text = sheetText(sheet, base, imports);
    if (text == null) continue;
    const style = document.createElement('style');
    style.textContent = [...imports, text].join('\n');
    (clone.querySelector('head') || clone).appendChild(style);
  }

  // Canvases, swapped for an image of what they show.
  const canvases = [];
  [...live.querySelectorAll('canvas')].forEach((c) => {
    let data;
    try { data = c.toDataURL('image/png'); } catch (_) { return; } // tainted: stays a canvas
    const el = twin(c);
    if (!el) return;
    const img = document.createElement('img');
    for (const a of el.attributes) img.setAttribute(a.name, a.value);
    img.setAttribute('width', String(c.width));
    img.setAttribute('height', String(c.height));
    img.setAttribute('src', `__PROOFS_CANVAS_${canvases.length}__`);
    if (!img.hasAttribute('alt')) img.setAttribute('alt', '');
    canvases.push(data);
    el.replaceWith(img);
  });

  // Form state the markup does not carry (typed by an action, set by a script). Hidden inputs are
  // blanked below: they hold tokens (authenticity_token), never anything a reader sees.
  liveAll.forEach((el, i) => {
    const c = cloneAll[i];
    if (!c || !clone.contains(c)) return;
    if (el.tagName === 'INPUT') {
      if (el.type === 'checkbox' || el.type === 'radio') { if (el.checked) c.setAttribute('checked', ''); else c.removeAttribute('checked'); }
      else if (el.type !== 'file' && el.type !== 'password') c.setAttribute('value', el.value);
    } else if (el.tagName === 'TEXTAREA') c.textContent = el.value;
    else if (el.tagName === 'OPTION') { if (el.selected) c.setAttribute('selected', ''); else c.removeAttribute('selected'); }
  });

  // <use href="sprite.svg#id"> pointing at another file. Chrome refuses an external <use> from a
  // file:// page ("'file:' URLs are treated as unique security origins") and from a data: URL, so
  // copying the sprite into the assets folder would leave the icon blank. Instead the referenced
  // element is copied into a hidden <svg> at the end of the body under a new id, and the <use>
  // points at that. A sprite that cannot be fetched (another origin, which the page could not use
  // either) keeps its absolute URL. References from the copied element to other parts of its sprite
  // are not followed.
  const sprites = new Map();
  const inlined = new Map();
  const defs = [];
  for (const el of clone.querySelectorAll('use')) {
    for (const attr of ['href', 'xlink:href']) {
      const v = el.getAttribute(attr);
      if (!v || v.trim().startsWith('#')) continue;
      const abs = resolve(v.trim(), base);
      if (!abs) continue;
      const u = new URL(abs);
      const frag = decodeURIComponent(u.hash.slice(1));
      u.hash = '';
      if (!sprites.has(u.href)) {
        let doc = null;
        try {
          const r = await fetch(u.href, { credentials: 'include' });
          if (r.ok) doc = new DOMParser().parseFromString(await r.text(), 'image/svg+xml');
        } catch (_) { /* another origin, or gone: keep the URL */ }
        sprites.set(u.href, doc);
      }
      const doc = sprites.get(u.href);
      const target = frag && doc ? doc.getElementById(frag) : null;
      if (!target) { el.setAttribute(attr, abs); continue; }
      if (!inlined.has(abs)) {
        const id = `proofs-use-${inlined.size + 1}`;
        const node = document.importNode(target, true);
        node.setAttribute('id', id);
        // What the copied element names was named by the sprite, not the page (see token).
        node.setAttribute('data-proofs-from', u.href);
        defs.push(node);
        inlined.set(abs, id);
      }
      el.setAttribute(attr, `#${inlined.get(abs)}`);
    }
  }
  if (defs.length) {
    const NS = 'http://www.w3.org/2000/svg';
    const holder = document.createElementNS(NS, 'svg');
    holder.setAttribute('aria-hidden', 'true');
    holder.setAttribute('style', 'position:absolute;width:0;height:0;overflow:hidden');
    const d = document.createElementNS(NS, 'defs');
    defs.forEach((n) => d.appendChild(n));
    holder.appendChild(d);
    (clone.querySelector('body') || clone).appendChild(holder);
  }

  // No code, and nothing that navigates, redirects or blocks the inlined sheets; no session token.
  clone.querySelectorAll('input[type="hidden" i]').forEach((el) => el.setAttribute('value', ''));
  clone.querySelectorAll('script, noscript, base, meta[http-equiv], meta[charset], meta[name="csrf-token" i], meta[name="csrf-param" i], '
    + 'link[rel~="preload"], link[rel~="modulepreload"], link[rel~="prefetch"], link[rel~="preconnect"], link[rel~="dns-prefetch"]')
    .forEach((el) => el.remove());
  const parseSrcset = (s) => {
    const out = [];
    let i = 0;
    while (i < s.length) {
      while (i < s.length && /[\s,]/.test(s[i])) i++;
      if (i >= s.length) break;
      let j = i;
      while (j < s.length && !/\s/.test(s[j])) j++;
      let url = s.slice(i, j), desc = '';
      if (url.endsWith(',')) { url = url.replace(/,+$/, ''); i = j; } else {
        let k = j, depth = 0;
        while (k < s.length && !(s[k] === ',' && depth === 0)) { if (s[k] === '(') depth++; if (s[k] === ')') depth--; k++; }
        desc = s.slice(j, k).trim();
        i = k + 1;
      }
      out.push({ url, desc });
    }
    return out;
  };
  for (const el of clone.querySelectorAll('*')) {
    const holder = el.closest('[data-proofs-from]');
    const from = holder ? holder.getAttribute('data-proofs-from') : base;
    for (const a of [...el.attributes]) {
      const name = a.name.toLowerCase();
      if (name.startsWith('on')) { el.removeAttribute(a.name); continue; }
      if (/^\s*javascript:/i.test(a.value)) { el.setAttribute(a.name, name === 'href' ? '#' : ''); continue; }
      if (name === 'style' && /url\(/i.test(a.value)) el.setAttribute(a.name, rewriteCss(a.value, from, 'a'));
    }
    const tag = el.tagName.toLowerCase();
    const swap = (attr) => {
      const v = el.getAttribute(attr);
      if (v == null) return;
      const t = asset(v, from, 'a');
      if (t) el.setAttribute(attr, t);
    };
    const swapSet = (attr) => {
      const v = el.getAttribute(attr);
      if (v == null) return;
      el.setAttribute(attr, parseSrcset(v).map(({ url, desc }) => (asset(url, from, 'a') || resolve(url, from) || url) + (desc ? ` ${desc}` : '')).join(', '));
    };
    const absolute = (attr) => {
      const v = el.getAttribute(attr);
      if (v != null && v.trim() && !v.trim().startsWith('#')) { const abs = resolve(v.trim(), base); if (abs) el.setAttribute(attr, abs); }
    };
    if (tag === 'img' || (tag === 'input' && (el.getAttribute('type') || '').toLowerCase() === 'image')) {
      if (!(el.getAttribute('src') || '').startsWith('__PROOFS_')) swap('src');
      swapSet('srcset');
    } else if (tag === 'source' && el.parentElement && el.parentElement.tagName.toLowerCase() === 'picture') {
      swap('src'); swapSet('srcset');
    } else if (tag === 'video') {
      swap('poster'); absolute('src');
    } else if (tag === 'image') {
      swap('href'); swap('xlink:href'); // the #fragment is kept after the asset path
    } else if (tag === 'a' || tag === 'area' || tag === 'link') {
      absolute('href');
      if (tag !== 'link') el.removeAttribute('target'); // target="_top" would navigate the review page
    } else if (tag === 'form') { absolute('action'); el.removeAttribute('target'); }
    else if (tag === 'iframe') {
      // A nested srcdoc is a whole page of HTML the script and on* stripping never saw, and it
      // would be same-origin with the review page: dropped, so the frame loads its src or nothing.
      el.removeAttribute('srcdoc');
      absolute('src');
    } else if (['embed', 'audio', 'source', 'track'].includes(tag)) absolute('src');
  }
  clone.querySelectorAll('[data-proofs-from]').forEach((el) => el.removeAttribute('data-proofs-from'));
  const head = clone.querySelector('head');
  if (head) {
    const meta = document.createElement('meta');
    meta.setAttribute('charset', 'utf-8');
    head.prepend(meta);
  }
  const dt = document.doctype;
  const doctype = dt ? `<!DOCTYPE ${dt.name}${dt.publicId ? ` PUBLIC "${dt.publicId}"` : ''}${dt.systemId ? `${dt.publicId ? '' : ' SYSTEM'} "${dt.systemId}"` : ''}>\n` : '';
  return { html: doctype + clone.outerHTML + '\n', urls, sheets, canvases };
}

const TYPE_EXT = {
  'image/png': '.png', 'image/jpeg': '.jpg', 'image/gif': '.gif', 'image/webp': '.webp', 'image/avif': '.avif',
  'image/svg+xml': '.svg', 'font/woff2': '.woff2', 'font/woff': '.woff', 'font/ttf': '.ttf', 'font/otf': '.otf',
  'application/font-woff2': '.woff2', 'application/font-woff': '.woff', 'text/css': '.css',
};

// "<hash>-<last path segment>", safe in a file name and in HTML and CSS without escaping.
function assetName(url, contentType) {
  const hash = crypto.createHash('sha1').update(url).digest('hex').slice(0, 10);
  let leaf = '';
  try { leaf = decodeURIComponent(new URL(url).pathname.split('/').pop() || ''); } catch (_) {}
  leaf = leaf.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[._]+/, '').slice(-60);
  if (!/\.[A-Za-z0-9]{2,5}$/.test(leaf)) leaf += TYPE_EXT[String(contentType || '').split(';')[0].trim().toLowerCase()] || '';
  return leaf ? `${hash}-${leaf}` : hash;
}

// Whether a file: URL may be read for a document at `from` (the page's URL for its own content, a
// sheet's URL for what that sheet names): only when that document is itself a file:. A page
// served over http, or a sheet from another site, that names file:///... would otherwise have a
// local file copied into the assets folder and published.
const fileAllowed = (url, from) => !/^file:/i.test(url) || /^file:/i.test(from || '');

// The bytes at a URL, with the page's cookies; null when they cannot be had, or when `url` is a
// file: and `from` is not (fileAllowed).
async function fetchAsset(page, url, from) {
  try {
    if (/^file:/i.test(url)) return fileAllowed(url, from) ? { body: fs.readFileSync(fileURLToPath(url)), type: '' } : null;
    const res = await page.context().request.get(url, { timeout: 15000 });
    if (!res.ok()) return null;
    return { body: await res.body(), type: res.headers()['content-type'] || '' };
  } catch (_) {
    return null;
  }
}

const escapeAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;');

// How deep @imports inside a fetched sheet are followed.
const IMPORT_DEPTH = 4;
const IMPORT_RULE = /@import\s+(?:url\(\s*(['"]?)([^'")]*)\1\s*\)|(['"])([^'"]*)\3)\s*([^;]*);/gi;

// A sheet the page could not read (another origin), fetched node-side with the page's cookies,
// the way assets are: { text, imports } with every url() resolved against the sheet's own URL
// and fetched through `asset` (the relative path, or null to keep the absolute URL), and each
// readable @import inlined in place (inside @media when it names one; its layer(...) and
// supports(...) are not carried, as for a readable sheet). imports holds the @import rules that
// could not be fetched, absolute, to hoist to the top of the <style>; `external` gets their URLs.
// null when the sheet itself cannot be fetched.
async function inlineSheet(page, href, asset, external, from, depth = 0) {
  if (!fileAllowed(href, from)) return null;
  const got = await fetchAsset(page, href, from);
  if (!got) return null;
  let text = got.body.toString('utf8').replace(/^\uFEFF/, '').replace(/@charset\s+(['"])[^'"]*\1\s*;/gi, '');
  const imports = [];
  const found = [];
  text = text.replace(IMPORT_RULE, (m, q1, u1, q2, u2, media) => {
    found.push({ m, href: new URL(u1 != null ? u1 : u2, href).href, media: media.trim() });
    return `__PROOFS_IMPORT_${found.length - 1}__`;
  });
  const inner = [];
  for (const f of found) {
    const sub = depth < IMPORT_DEPTH ? await inlineSheet(page, f.href, asset, external, href, depth + 1) : null;
    if (!sub) {
      imports.push(`@import url("${f.href}")${f.media ? ` ${f.media}` : ''};`);
      if (!external.includes(f.href)) external.push(f.href);
      inner.push('');
      continue;
    }
    imports.push(...sub.imports);
    const media = f.media.replace(/\b(layer|supports)\([^)]*\)\s*/gi, '').replace(/^layer\b\s*/i, '').trim();
    inner.push(media ? `@media ${media} {\n${sub.text}\n}` : sub.text);
  }
  text = text.replace(/__PROOFS_IMPORT_(\d+)__/g, (m, i) => inner[i]);
  const urls = [];
  text.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (m, q, u) => { urls.push(u); return m; });
  const rel = new Map();
  for (const u of urls) {
    const t = u.trim();
    if (!t || /^(data|blob|about|javascript):/i.test(t) || t.startsWith('#') || rel.has(t)) continue;
    let abs;
    try { abs = new URL(t, href).href; } catch (_) { continue; }
    const hash = abs.indexOf('#');
    const bare = hash >= 0 ? abs.slice(0, hash) : abs;
    const r = /^(https?|file):/i.test(bare) ? await asset(bare, href) : null;
    rel.set(t, (r || bare) + (hash >= 0 ? abs.slice(hash) : ''));
  }
  text = text.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (m, q, u) => (rel.has(u.trim()) ? `url("${rel.get(u.trim())}")` : m));
  // Its text goes inside a <style>, which only "</style" can end.
  return { text: text.replace(/<\/(style)/gi, '<\\/$1'), imports };
}

async function snapshotPage(page, outDir, name) {
  const snap = await page.evaluate(collectSnapshot);
  const file = `${name}-snapshot.html`;
  const folder = `${name}-snapshot-assets`;
  const dir = path.join(outDir, folder);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const assets = [];
  let bytes = 0;
  const write = (leaf, body) => {
    const rel = `${folder}/${leaf}`;
    if (!assets.includes(rel)) {
      fs.writeFileSync(path.join(dir, leaf), body);
      assets.push(rel);
      bytes += body.length;
    }
    return rel;
  };
  // One fetch per URL, for the page's own references and the fetched sheets' alike.
  const fetched = new Map();
  // A file: URL a document may not read (fileAllowed) is never fetched: it keeps its absolute
  // URL and is listed in `external`.
  const external = [];
  const assetPath = async (url, from) => {
    if (!fileAllowed(url, from)) {
      if (!external.includes(url)) external.push(url);
      return null;
    }
    if (!fetched.has(url)) {
      const got = await fetchAsset(page, url, from);
      fetched.set(url, got ? write(assetName(url, got.type), got.body) : null);
    }
    return fetched.get(url);
  };
  const pageUrl = page.url();
  const paths = [];
  // Each against the document that named it (collectSnapshot's token), never just the page.
  for (const u of snap.urls) paths.push(await assetPath(u.url, u.from || pageUrl));
  // Sheets from another origin: inlined like the page's own, since a published page loads
  // no stylesheet from another site but Google Fonts. One that cannot be fetched stays an
  // @import of its absolute URL and is listed in `external`.
  const sheets = [];
  for (const sh of snap.sheets) {
    const got = await inlineSheet(page, sh.href, assetPath, external, pageUrl);
    if (!got) {
      if (!external.includes(sh.href)) external.push(sh.href);
      sheets.push({ imports: [`@import url("${sh.href}")${sh.media ? ` ${sh.media}` : ''};`], text: '' });
    } else sheets.push({ imports: got.imports, text: sh.media ? `@media ${sh.media} {\n${got.text}\n}` : got.text });
  }
  const canvasPaths = snap.canvases.map((data, i) =>
    write(`canvas-${i + 1}.png`, Buffer.from(data.slice(data.indexOf(',') + 1), 'base64')));
  const html = snap.html
    .replace(/__PROOFS_ASSET_([as])_(\d+)__/g, (m, ctx, i) => paths[i] || (ctx === 'a' ? escapeAttr(snap.urls[i].url) : snap.urls[i].url))
    .replace(/__PROOFS_CANVAS_(\d+)__/g, (m, i) => canvasPaths[i])
    // Each <style> with a sheet token: the @imports left unfetched go first, where @import must be.
    .replace(/(<style\b[^>]*>)([\s\S]*?)(<\/style>)/g, (m, open, body, close) => {
      if (!body.includes('__PROOFS_SHEET_')) return m;
      const hoist = [];
      const text = body.replace(/__PROOFS_SHEET_(\d+)__/g, (t, i) => { hoist.push(...sheets[i].imports); return sheets[i].text; });
      return open + [...hoist, text].join('\n') + close;
    });
  fs.writeFileSync(path.join(outDir, file), html);
  bytes += Buffer.byteLength(html);
  if (!assets.length) fs.rmdirSync(dir);
  return { file, assets, bytes, canvases: snap.canvases.length, external };
}

module.exports = { snapshotPage, collectSnapshot, assetName };
