# Changelog

- **1.1.2** (2026-11-19): Delivers the page as "Where the page goes" says rather than always via artifacts. Says plainly that it needs the whole plugin. Candidate images used in several places are embedded once.
- **1.1.1** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.1.0** (2026-11-18): The gallery is now built by the shared, tested builder (`shared/review_page`), with images embedded from `assets` and a smoke test that fails on any image that did not load. Same page and export for the reviewer.
- **1.0.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.0.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. Worked example uses neutral topics.
- **1.0.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.0.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
