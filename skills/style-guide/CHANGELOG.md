# Changelog

- **1.6.2** (2026-11-19): Delivers the page as "Where the page goes" says rather than always via artifacts. Says plainly that it needs the whole plugin.
- **1.6.1** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.6.0** (2026-11-18): The audit page is now built by the shared, tested builder (`shared/review_page`): Claude writes the rendered examples, the builder supplies the four decisions, Works as Designed, legend, category filters, light/dark preview switch, export and clipboard fallback. An accepted undecided item now names its option.
- **1.5.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.5.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust.
- **1.5.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.5.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
