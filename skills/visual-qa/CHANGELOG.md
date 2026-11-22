# Changelog

- **1.3.0** (2026-11-22): Runs its scripts (`capture.cjs`) through `${CLAUDE_PLUGIN_ROOT}` and pre-approves them and reads of the plugin's own files, so a session no longer asks permission for each one.
- **1.2.0** (2026-11-19): Its review page sets `"skill": "visual-qa"`, so the header's pill names this skill rather than design-review, and fills `project.session`.
- **1.1.5** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.1.4** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.1.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.1.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. Framework-neutral wording for partial-page updates; invocation is `/proofs:visual-qa`.
- **1.1.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.1.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
