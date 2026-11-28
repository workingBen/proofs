# Proofs brand

How Proofs itself looks: the website, the README banner, link previews, the tab icon, card
pictures and videos. Follow it for anything new that carries the Proofs name.

(The `style-guide` skill is something else: it settles design rules for *your* site. This file is
Proofs' own look.)

## Colors

| Name | Light | Dark | Used for |
|---|---|---|---|
| band | `#15130f` | `#15130f` | the dark top band (bottom of its gradient), favicon |
| band top | `#2f2719` | `#2f2719` | the lighter top-right corner of the band |
| orange | `#c2410c` | `#ff8a4c` | accent: the italic o, links, buttons, selected tiles |
| orange on dark | `#ff8a4c` | `#ff8a4c` | accent on the band, in both modes; text on it is `#1b130c` |
| paper | `#f4efe6` | `#15130f` | page background below the band |
| card | `#fffdf9` | `#1e1b16` | cards and panels |
| ink | `#1d1b17` | `#efe8dc` | body text (`#efe8dc` is also the text color on the band) |
| muted | `#6b6458` | `#a69d8e` | secondary text, mono labels (`#a69d8e` on the band) |
| line | `#ddd5c6` | `#3a352c` | rules and borders (`#3a352c` on the band) |
| note cream | `#f8f5ee` | `#f8f5ee` | the cream pinned note; text on it is `#1f2a24` |

The full light and dark token sets live at the top of `site-src/skillpage_tpl.html`.

## Type

- **Wordmark:** "proofs" in a serif, with the second o in orange italic: `pro<i>o</i>fs`.
  Instrument Serif on the site; Georgia in the README banner, the card picture and anywhere
  webfonts can't load.
- **Headlines:** Instrument Serif on the site. Newsreader in long-form articles.
- **Labels:** JetBrains Mono, capitals, wide letter spacing (about 0.14em).
- **Body:** the system sans (`-apple-system, "Segoe UI", Helvetica, Arial, sans-serif`).
- **SVGs shown on GitHub** (the banners) are images, so no webfonts: use
  `Georgia, 'Times New Roman', serif`, `ui-monospace, Menlo, monospace` and the system sans.

## The band

The top of the home page sits on a warm dark band, **always dark, in light mode too**:

```css
background: radial-gradient(110% 130% at 88% 0%, #2f2719 0%, #231e15 42%, #18150f 75%, #121009 100%);
```

On the band: text `#efe8dc`, lede `#d8cfbf`, muted labels `#a69d8e`, orange `#ff8a4c` (eyebrow,
the italic word in the headline), code boxes `#0b0a08` with a `#3a352c` border, orange Copy
buttons with dark `#1b130c` text, and a `#3a352c` rule under the top bar.

Below the band, pages stay on the warm paper and follow the visitor's light or dark setting.
The README banner is the band in miniature, and is the same picture in GitHub's light and dark
modes.

## Pinned notes

Small tilted notes, like the comments a reviewer leaves on a review page:

- **PICK** notes are orange (`#ff8a4c`, dark text), tilted -4 degrees. Example: `PICK 1` /
  **Variant B**.
- **NOTE** notes are cream (`#f8f5ee`, dark text), tilted +3 degrees. Example: `NOTE 2` /
  **Make the button lighter orange**.
- A mono label in capitals over one bold line, rounded corners, a soft shadow.
- At most two per view. They are decoration (`aria-hidden`), so they never cover a control (the
  play button, a Copy button) and never carry information the page doesn't also say.
- A PICK note sits on the thing it picks: on the home page video it is over the AFTER half of
  the before/after picture.

## Card pictures

- 1200&times;630. The wordmark and tagline on the left, on the band; a cream review-page panel
  on the right (two variant tiles, B selected with an orange border); at most two pinned notes.
- The current card is `docs/assets/social-card.jpg`: the website's link preview (`og:image`)
  and the picture to upload as the repo's social preview (GitHub: Settings, then Social preview).
- Source: `assets/card/render.cjs`. Its header says how to run it and convert the result.
  Every Chrome launch passes `--disable-features=MacAppCodeSignClone`.

## Tab icon

`site-src/media/favicon.svg`: a 32&times;32 rounded square in `#15130f` with an orange
(`#ff8a4c`) italic Georgia o. `apple-touch-icon.png` (180&times;180) is the same mark, square.
The build copies both, and the card, into `docs/assets/`.
