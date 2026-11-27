# Spike: srcdoc iframe for design-review Refine mode (2026-11-26)

Page: `2026-11-26-srcdoc-frame.html`. Check: `node docs/superpowers/spikes/2026-11-26-srcdoc-frame-check.cjs`.

Two `srcdoc` iframes (1280 wide scaled with `transform: scale()`, and 390 wide). The inner page has a
`max-width: 600px` media query that changes a heading's color, and a rule scoped under
`html[data-rc~="c1"]`. An outer button toggles `data-rc` on each frame's `contentDocument.documentElement`
and the outer page prints each frame's computed heading color with a PASS/FAIL line per check.

## file:// (headless Chromium via launchChromium, viewport 390)

Result: PASS, 15 of 15 checks (before toggle, after toggle, toggled back).

- 1280 frame: inner width 1280, desktop color rgb(0, 128, 0)
- 390 frame: inner width 390, phone color rgb(200, 0, 0) (media query fires per frame, not per outer page)
- Toggle: both frames turn rgb(128, 0, 128); toggling again restores both
- No sideways scroll on the 390-wide outer page

## Artifact and iPhone: pending controller

To record: does it render, does the toggle work, are both widths correct (artifact, then Ben's iPhone).
A sandboxed artifact origin may block `contentDocument` access; the page reports that as `ERROR ...`.

## Decision

Provisional: `iframe` (file:// passes). Final decision waits on the artifact and iPhone results;
if any fails, record `container-queries` with what failed.
