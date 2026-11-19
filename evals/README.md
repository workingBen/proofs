# Skill trigger evals

Does the right skill fire for a real request, and does it stay quiet when a sibling
is the right one? 50 cases, run with `claude plugin eval`:

- **fire-<skill>-1, -2:** two everyday requests that should fire that skill.
- **miss-<skill>:** a near miss meant for its nearest sibling (questions vs
  qa-checklist, design-review vs visual-qa, pr-qa vs visual-qa, todos vs
  review-cycle, …). It passes only if the sibling fires and this skill does not.
- **ambiguous-<name>:** a request a reasonable person could word either way. Each
  names the one right skill and why (`AMBIGUOUS` in `make_cases.py`); it passes only
  if that skill fires and no other proofs skill does. Genuine coin flips were dropped.
- **none-<name>:** a plain coding request; no proofs skill should fire.

The cases are generated from `make_cases.py`; edit `CASES` there and rerun it rather
than editing the folders by hand.

```bash
python3 evals/make_cases.py
claude plugin eval . --ablation none -j 6 --no-publish
```

`--ablation none` because the score here is which skill fired; a no-plugin arm has
no skills to fire. Each case runs 3 times. `results/` is ignored by git.

## Last run

2026-11-19, Claude Code 2.1.311, 3 runs per case, `-j 6`, 4 min 56 s:

- **Everyday requests (fire- and miss-): 108 of 108 runs passed.** Every skill 6 of 6
  on its own requests and 3 of 3 on its near miss.
- **Harder round (ambiguous- and none-): 42 of 42.** The three plain coding requests
  fired no skill (9 of 9), and all eleven ambiguous cases passed 3 of 3. The one
  miss in the previous run, `ambiguous-ask-later` (several decisions to answer later
  from a phone, expected `questions`), was fixed by sharpening the `questions` and
  `working-log` descriptions; it then passed 6 of 6 on its own.
