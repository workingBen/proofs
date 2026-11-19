# Changelog

- **1.4.5** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.4.4** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.4.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.4.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. The session reminder now ships as a plugin hook that stays off until `PROOFS_PR_REMINDER=1` is set (the installer sets it); no path is written into project settings. Invocations use `/proofs:pr-qa`.
- **1.4.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.4.0** — Merged into proofs: generic, no project-specific steps.
