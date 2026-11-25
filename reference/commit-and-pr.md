# Commit, push and pull request

Read this before any skill commits, pushes or opens a pull request (design-review when asked
to commit, review-cycle per item, pr-qa when it merges). The project's own notes (`CLAUDE.md`)
come first where they say something different; this covers what they usually leave out. Astro
run 3 is where each rule comes from: the commit session staged with `git add -A .`, its push
failed and it stalled waiting for an approval it could not get, and its PR body listed only file
names.

## 1. Stage the files you changed, by name

Run `git status --short`, then `git add <path> <path>` with each file this work changed. Never
`git add -A`, `git add .` or `git commit -a`: they also take anything else in the folder (a
stray `.env`, a build folder that is not ignored, another session's edits). A lockfile an
install rewrote stays out unless the change needs it (`git restore` it, and say so).

One command per Bash call: no `&&`, `;` or pipes, and no `| tail` after a push. Permission
rules match the whole command, so a chain asks for approval (and `claude -p` refuses it) even
when each part is allowed.

Write the commit message with the Write tool to `.proofs/commit-msg.txt` and commit with
`git commit -F .proofs/commit-msg.txt`, or use `git commit -m "<subject>" -m "<body>"`.

## 2. Push once; when it fails, say so plainly

```text
git push -u origin HEAD
```

(Allowed by the README's opt-in `--commit` block, like every git line here; without it each asks.)

If it fails, read the error and take **at most one retry** from this list, then stop:

| The error says | What it usually means | The one retry |
|---|---|---|
| `HTTP 400`, `RPC failed`, `unexpected disconnect`, `the remote end hung up` | A large pack sent over HTTP/2, often because the remote moved and git has no recent base to send less against | `git fetch origin`, then `git push -u origin HEAD` again; if that fails the same way, `git -c http.postBuffer=524288000 push -u origin HEAD` |
| `rejected`, `non-fast-forward`, `fetch first` | The remote branch has commits you do not | none: never force-push; say so |
| `403`, `401`, `Permission denied`, `Authentication failed` | Credentials | none |
| The command needs approval or was refused | Not in the allow rules | none: do not try other spellings of it |

When the retry fails or none applies, **end the turn with a plain report**, in chat (and on the
working log, when the session has one): what is done (`commit <sha> on <branch>`), what failed
(the first error line, quoted), and **the exact command** that would finish it, one per line, for
the user to approve or run. **Do not open the pull request** until the branch is on the remote:
`gh pr create` refuses it, and the refusal only adds noise. Diagnostics (`git count-objects`,
`git ls-remote`) are not needed to write this report.

The README's `--commit` block allows the plain push, the larger-buffer push and `git fetch origin`
comes with `--project`. It does not allow `git config`: a setting written there persists, and can
set an alias or a hooks folder that runs anything.

## 3. A real PR body: what, why, how it was checked

Write the body with the Write tool to `.proofs/pr-body.md`, then
`gh pr create --title "<title>" --body-file .proofs/pr-body.md`. The body has three short parts,
and never only file names (`gh pr create --fill` writes just the commit subjects):

- **What changed**: one line per change a person would see ("The hero is two columns from
  1040 px up"), plus any change that is not visible but matters (a new type, a removed file).
- **Why**: the request, the picks or the bug it comes from (for design-review, the item numbers
  and variants accepted).
- **How it was checked**: the build, the type check and the tests that ran, with their results;
  the capture's widths and what it found (numbers, and any entries new since the earlier capture);
  and what was **not** checked, named.

End it with the attribution lines the project or session asks for, if any. When the change left
a lockfile out, or a check failed and was left, say that in the body too.
