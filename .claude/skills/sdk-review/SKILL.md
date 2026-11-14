---
name: sdk-review
description: Review an SDK change before its pull request. Several OpenAI reviewers (Codex, read-only) look at it in parallel, then Claude checks every finding against the code and sorts it into fix-now / improve-now / later / not-an-issue.
---

# /sdk-review: outside reviewers, one honest triage

Use it before opening a pull request that adds or changes an SDK, the spec or the examples. Two
stages, two models:

1. **Find** (OpenAI `gpt-5.6-sol` through the Codex CLI, one reviewer per part, read-only, in the
   background). Each reviewer owns one PART of the change and returns a ranked list of findings.
   One extra reviewer owns SECURITY across all parts.
2. **Triage** (Claude, this session). Every finding is checked against the real code, one at a time,
   and sorted into four lists. The user decides what gets fixed; nothing is fixed inside this skill.

The reviewers all get the same rules, in `DIRECTIONS.md`: report bugs, security, silent mistakes,
gaps with `spec/openapi.yaml` and rare strong improvements; never style, tests, docs or refactors.

## How to run it

### 1. Scope the change
```bash
git diff --stat main...HEAD          # committed work on the branch
git diff --stat --cached             # or the staged work, before the commit
```

### 2. Split into parts
One reviewer per part. A part = one SDK (or the spec) with its tests and examples, 1 to 15 files.
Always add the **security** part (all changed files, attacker view). Write `parts.tsv` OUTSIDE the
repo (the script refuses a path inside it), one part per line, tab separated:
```
name<TAB>doc(s) to read first<TAB>files (space separated, globs allowed)<TAB>focus for this part
```
`parts.example.tsv` shows the shape. Keep the focus concrete: what can go wrong HERE (retries,
streaming, paging, which fields go on the wire). Do not restate the general directions.

### 3. Run
```bash
bash .claude/skills/sdk-review/scripts/run.sh <parts.tsv>     # out dir: ~/.cache/sdk-review/<date>
```
It runs every part through `codex exec -m gpt-5.6-sol -c model_reasoning_effort=high -s read-only` in
parallel and writes `<out dir>/<part>.md` per reviewer plus `_done.txt`. Run it in the background
(10 to 30 minutes). It needs `OPENAI_API_KEY`; Codex gets its own config directory under `~/.cache`,
so the user's own Codex login is never touched. Cost: about $1 to $2 per part. Ask the user before
running it, since it spends money.

**This repository is public.** The out dir, the parts file and the reviewer transcripts stay outside
it. Never put an env file or a key file in a part.

### 4. Triage (Claude, one finding at a time)
For EVERY finding, open the cited code and decide. Never take the reviewer's word; never batch. Sort:

| list | meaning |
|---|---|
| **A · fix before merge** | a real bug, a security hole, a key leak, silently wrong data, a spec gap |
| **B · strong improvement, do now** | not a bug, but we would regret shipping without it; say why not "later" |
| **C · later** | real but small, or needs a design decision; goes to the board |
| **D · not an issue** | the reviewer misread the code; say the line that proves it |

Merge duplicates across reviewers. Keep the reviewer's confidence and add yours.

### 5. Deliver
One finding = four lines, numbered ACROSS the lists (A1..An, then B continues the count), so "fix 3"
names one thing in every conversation:

1. **The title, bold, one sentence that states the fault as a fact.** Not a label, not a question.
2. The place: `file · function`. No line numbers: they drift.
3. Two or three plain sentences for a reader who has not seen the code: what happens, with a real
   input, and what comes out wrong.
4. `fix ·` one line: the change, concrete enough to start from.

A D finding keeps lines 1 to 3; line 3 names the code that proves the reviewer wrong. The C list may
be compact (title + place + one clause).

- In chat: the counts per list and the A list in full. Then STOP. The user picks what to fix.
- In the pull request description: a short "Review" section with the counts and what was fixed.

## Invariants
- The outside model FINDS; it never writes the fix. Claude VERIFIES; it never fixes inside this skill.
- Read-only sandbox for every reviewer. The reviewers never see secrets.
- The directions are the same for every run. Change them in `DIRECTIONS.md`, not per run.
- Prefer fewer, sharper findings.
