# Spike: srcdoc iframe for design-review Refine mode (2026-11-26)

Page: `2026-11-26-srcdoc-frame.html`. Check: `node docs/superpowers/spikes/2026-11-26-srcdoc-frame-check.cjs`.

Two `srcdoc` iframes (1280 wide scaled with `transform: scale()`, and 390 wide). The inner page has a
`max-width: 600px` media query that changes a heading's color, and a rule scoped under
`html[data-rc~="c1"]`. An outer button toggles `data-rc` on each frame's `contentDocument.documentElement`
and the outer page prints each frame's computed heading color with a PASS/FAIL line per check.

## file:// (headless Chromium via launchChromium, viewport 390)

Result: PASS, 34 of 34 checks (both-frame and single-frame toggles, data-rc c2 and "c1 c2", and a not-loaded frame reporting FAIL).

- 1280 frame: inner width 1280, desktop color rgb(0, 128, 0)
- 390 frame: inner width 390, phone color rgb(200, 0, 0) (media query fires per frame, not per outer page)
- Toggle: both frames turn rgb(128, 0, 128); toggling again restores both
- No sideways scroll on the 390-wide outer page

## Artifact and iPhone: PASS (2026-11-26)

Published as a claude.ai artifact (version 2, with the not-loaded and scoped-toggle checks). The owner opened it on an iPhone and tapped every button: every line PASS. Both frames loaded, each kept its own width's layout, and the outer page could reach each frame's `contentDocument` to toggle `data-rc`.

## Decision

**`iframe`.** Every check passed via file://, in a published artifact, and on an iPhone. Tasks 3 and 4 build `srcdoc` iframes. Set `data-rc` after each frame's `load` event: a `srcdoc` load replaces the document.
