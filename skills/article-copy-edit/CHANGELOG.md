# Changelog

- **1.3.1** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.3.0** (2026-11-18): The review page is now built by the shared, tested builder (`shared/review_page`): Claude writes the spec and the Original/Edit panes, the builder supplies the four decision buttons, sticky tally, export and clipboard fallback. Same page and export for the reviewer; a plain accept exports as `ACCEPT (Use Edit)`.
- **1.2.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.2.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust.
- **1.2.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.2.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
