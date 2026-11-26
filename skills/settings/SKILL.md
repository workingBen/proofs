---
name: settings
version: 1.0.0
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
description: Use when the user wants to see or change Proofs settings ("open Proofs settings", "change the port", "turn on the spelling check") on a page with real controls, a save bar and Send to Claude. Writes only PROOFS_ keys in a settings file, never permissions. Differs from questions, which asks decisions, not options.
---

# Settings

The Proofs settings on one page. The user changes values there, taps **Send to Claude**,
and you write them to the right settings file.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Every setting, its default, range and file: `../../reference/settings.md`. The page's
layout and database rows: "`settings` mode" in `../../reference/review-page.md`.

**Rules that never bend.**

- Write only keys that start with `PROOFS_`, and only through `shared/settings.py`.
- Never touch permissions, hooks or any other key in a settings file.
- No setting lowers a check. The text and tap floors can only go up.
- Do not edit a settings file by hand.

## Opening the page

Say "open Proofs settings", or run `/proofs:settings`.

1. Make the spec: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --spec --out .proofs/settings/spec.json`. It holds every setting with its value now and where that value came from.
2. Build it: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py .proofs/settings/spec.json --out .proofs/pages/settings.html`.
3. Run `--smoke` on the page: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py --smoke .proofs/pages/settings.html`. If it reports Playwright missing, run the one-line install it prints, then run it again. If it still cannot run, say so in chat.
4. Publish `.proofs/pages/settings.html` as an artifact with `capabilities: {"db": {}, "comments": {}}`. Give the user the URL in chat.

On a later open, rebuild from a fresh `--spec` and republish to the **same file path**, so the URL stays the same.

## When the user sends changes

A **Send to Claude** tap wakes this session. The page saves each change as a row in its database.

1. List `proofs-answers` with `ArtifactData` `list` and `out_dir`.
2. Dry run: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --apply <out_dir> --dry-run`. Read what would apply and what would be skipped.
3. Apply: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --apply <out_dir>`. **Exit 1 (from the dry run or the apply) is not a stop.** It means at least one row was skipped: the other rows still apply, so run the apply anyway, then report each `SKIPPED` line in chat and on the page (as a short note above the settings when you rebuild), and republish as usual.
4. **Republish first, before anything else.** Run `--spec --out` again, rebuild, and republish to the same file path. The page version changes, and the page says "Claude picked up your answers". That is the user's confirmation. The page cannot read your chat.
5. Show every `APPLIED` and `SKIPPED` line in chat.
6. Never post a second reply in the thread. Resolve the thread with `ArtifactComments`.

A row is skipped when its value is out of range, its key is unknown, it carries no shown
value (`from`), or the setting changed since the page was built. The line says which. A
skipped row is not an error to fix by hand: tell the user, and they can change it again on
the fresh page.

**`SKIPPED KEY: still overridden by <source> file (<path>)`** means the value was written,
but a narrower file (or, for a reset, another file) still sets that key, so nothing changed.
Tell the user in plain words: "Your change to <label> was saved to <scope> settings, but
<path> also sets it, and that file wins. Remove it there, or change it at that level." Do
not edit that file yourself unless the user asks; then use `settings.py --unset KEY --scope
<source>`.

Resetting the browser or Playwright folder to `auto`, or the pr-qa base folder to its
default, removes the key from the file (the line says "removed from"), because those
values mean "not set".

A change the user undid on the page is ignored.

## What the user should know

- A new value is saved at once, but a running session still has the old one in its environment. Restart Claude Code to pass it to hooks. The page says so.
- A setting saved in the project file is committed with the project. Tell the user which file each line wrote to.
- If the user only says "set the port to 3099", skip the page: run `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --set PROOFS_PORT=3099` and show the result.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.

## Common mistakes

| Mistake | Why it fails |
|---|---|
| Editing `.claude/settings.json` by hand | You can break a file that holds permissions and hooks. `settings.py` keeps every other key |
| Replying in the thread after a send | The harness already replied; a second reply is noise |
| Applying without a dry run | A stale row silently overwrites a change made elsewhere |
| Not republishing after an apply | The page keeps showing the old values and the user thinks nothing happened |
| Writing a value the page refused | The page shows the reason; do not work around it |
