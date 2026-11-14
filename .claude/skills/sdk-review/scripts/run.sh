#!/bin/bash
# Runs one OpenAI reviewer per part, in parallel, read-only, and writes <out>/<part>.md each.
# Usage: run.sh <parts.tsv> [out dir]   (parts.tsv: name \t docs \t files \t focus, one part per line)
# The out dir defaults to ~/.cache/sdk-review/<date>: OUTSIDE the repo. Reviewer transcripts and
# Codex's config (it holds the API key) must never land in this public tree.
# Needs: codex CLI on PATH, OPENAI_API_KEY in the environment. Codex gets its own config directory
# so the user's own Codex login is never read or changed.
set -u
PARTS=${1:?parts.tsv}; OUT=${2:-${XDG_CACHE_HOME:-$HOME/.cache}/sdk-review/$(date +%Y-%m-%d-%H%M)}
MODEL=${SDK_REVIEW_MODEL:-gpt-5.6-sol}; EFFORT=${SDK_REVIEW_EFFORT:-high}
SKILL=$(cd "$(dirname "$0")/.." && pwd); REPO=$(git rev-parse --show-toplevel)
CODEX_HOME=${XDG_CACHE_HOME:-$HOME/.cache}/sdk-review/codex-home
# The transcripts, the parts file and Codex's config (it holds the key) must stay out of this public repo.
python3 - "$REPO" "$OUT" "$PARTS" "$CODEX_HOME" <<'PY' || exit 2
import os, sys
repo, *paths = (os.path.realpath(p) for p in sys.argv[1:])
for p in paths:
    if os.path.commonpath([repo, p]) == repo:
        sys.exit(f"{p} must be outside the repo ({repo})")
PY
mkdir -p "$OUT/tasks" "$CODEX_HOME"; chmod 700 "$CODEX_HOME"
[ -n "${OPENAI_API_KEY:-}" ] || { echo "OPENAI_API_KEY is not set" >&2; exit 2; }
python3 - "$CODEX_HOME/auth.json" <<'PY'
import json, os, sys; json.dump({"auth_mode": "apikey", "OPENAI_API_KEY": os.environ["OPENAI_API_KEY"]}, open(sys.argv[1], "w"))
PY
chmod 600 "$CODEX_HOME/auth.json"; export CODEX_HOME
echo "reviewers write to $OUT"
: > "$OUT/_done.txt"; cd "$REPO"
while IFS=$'\t' read -r name docs files focus; do
  [ -n "$name" ] && [ "${name:0:1}" != "#" ] || continue
  expanded=$(for f in $files; do ls -d $f 2>/dev/null; done | tr '\n' ' ')
  { cat "$SKILL/DIRECTIONS.md"; printf "\n# Your part: %s\nDoc(s) to read first: %s\nFiles to review (all of them, fully):\n%s\nFocus for this part: %s\n" "$name" "$docs" "$expanded" "$focus"; } > "$OUT/tasks/$name.md"
  # perl's alarm stands in for `timeout`, which macOS does not ship: 40 minutes per reviewer.
  ( perl -e 'alarm shift; exec @ARGV' 2400 codex exec -m "$MODEL" -c model_reasoning_effort="$EFFORT" -s read-only -o "$OUT/$name.md" "$(cat "$OUT/tasks/$name.md")" < /dev/null > "$OUT/tasks/$name.log" 2>&1
    echo "$name exit $?" >> "$OUT/_done.txt" ) &
done < "$PARTS"
wait; echo "ALL DONE" >> "$OUT/_done.txt"
for f in "$OUT"/*.md; do printf "%-22s %s\n" "$(basename "$f" .md)" "$(grep -oE '^total: .*' "$f" | tail -1)"; done
