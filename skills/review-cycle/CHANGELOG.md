# Changelog

- **1.11.2** (2026-11-18): Checkpoints, The Tracking Page and End-of-Session Summary moved to `reference/` files in this skill's folder, each read when it applies (their Common Mistakes rows moved with them); SKILL.md keeps a short pointer and the trigger list. No change in behavior.
- **1.11.1** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.11.0** (2026-11-17): Triage. Every item gets one lane (Fix, Design review, Visual QA, Copy edit, Photo, Style rule, To-do, Needs input), and the lane starts the matching skill in this plugin automatically: a design call becomes a published design review, a big feature becomes a to-do. Two new card states: In design review, Saved as a to-do.
- **1.10.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. The superpowers skills are optional, with a plain fallback when they are not installed.
- **1.10.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.10.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
