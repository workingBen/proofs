# Changelog

- **1.3.2** (2026-11-26): Reads its numbers and paths from the Proofs settings (`settings.py --print`) instead of fixed values; the defaults are unchanged.
- **1.3.1** (2026-11-24): **Results first** (the maintainer's principle): nothing matters more than a result the user wants; save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs. Full text is rule 0 in `reference/house-rules.md`.
- **1.3.0** (2026-11-22): Runs its scripts (`todos_page.py`) through `${CLAUDE_PLUGIN_ROOT}` and pre-approves them and reads of the plugin's own files, so a session no longer asks permission for each one.
- **1.2.0** (2026-11-19): The project bar starts with the proofs mark and a `todos` pill, then project · session · repo; the "Todos" label is gone. New `--session NAME` flag on `todos_page.py`; without it the page builds and says it has no session.
- **1.1.5** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.1.4** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.1.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.1.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. Default page path is `.proofs/pages/todos.html`.
- **1.1.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.1.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
