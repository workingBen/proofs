# House rules

Four rules for every proofs skill that captures pages or builds a page. The skills repeat the short form; this is the full text and the reason.

1. **Finish in this turn.** Build, smoke-check and screenshot before you reply; the next turn re-reads the whole session and costs more each time. Write big files (HTML, spec JSON, scripts) with the Write tool and never print them back with `cat`, `head` or `Read`; the helpers print short summaries.
2. **Stay in two folders.** Read only inside the project (the folder Claude Code started in) and the plugin folder. Do not read parent folders: their `CLAUDE.md` is already loaded for you. Write specs, scratch scripts, screenshots and pages only under `.proofs/` in the project, never the system temp folder, `$TMPDIR` or `~`. The exceptions are the Playwright install in `~/.cache/proofs-playwright` and pr-qa's `PROOFS_BASE_DIR` base folder, when it is set.
3. **One command per Bash call.** No pipes, redirects, `;`, `&&`, `cd`, `$(...)` or `VAR=` in front: Claude Code matches its allow rules against the whole command, and any of those makes it ask (or, in `claude -p`, refuse).
4. **Use the helpers' own checks, not ad hoc tools.** Capture prints each shot's size and overflow; `review_page.py --check` and `--smoke` check a page. Change your own files with the Edit or Write tool, never `sed -i`. Do not run `file`, `magick`/`identify` or `sips`.

## Why

- A prompt that waits for an approval ends the turn. The next turn pays for the whole session again, so a review that stops three times costs about four times as much.
- Parent folders and `/tmp` are outside the allow rules, so each read or write there is a prompt.
- A compound command is matched as one string, so a pipe or a `VAR=` prefix turns an allowed command into one that asks.
