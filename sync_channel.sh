#!/usr/bin/env bash
# Per-channel pipeline: detect new stand.fm episodes → download → then, PER
# EPISODE: transcribe → (in background) summarize → rebuild site → publish.
#
# Pipelined: while whisper holds the GPU for episode N+1, episode N's
# summarize/build/push chain runs concurrently. Each finished episode appears
# on the published page without waiting for the rest of the backlog.
# Summaries run in parallel safely (distinct files); build+push is serialized
# with flock so concurrent chains never race the git worktree.
#
# Channel paths/backend/repo come from channels.json via `channels.py env` —
# no hardcoded layout. Every stage is idempotent, safe to run on a timer.
#
# Usage:
#   ./sync_channel.sh <slug-or-id>        # e.g. ./sync_channel.sh tocchirakari
#   NO_PUBLISH=1 ./sync_channel.sh <slug> # build everything but don't git push
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$PWD"

[ $# -ge 1 ] || { echo "usage: $0 <channel-slug-or-id>" >&2; exit 2; }
eval "$(python3 "$ROOT/channels.py" env "$1")"
[ "$CH_ENABLED" = "1" ] || { echo "channel $CH_SLUG is disabled — skipping."; exit 0; }
echo "=== $CH_NAME ($CH_SLUG) ==="

mkdir -p "$CH_DIR/transcripts"
PUBLISH_LOCK="$CH_DIR/.publish.lock"

summarize() {  # $1: --only filter (optional)
  python3 "$ROOT/summarize_episodes.py" \
    -t "$CH_DIR/transcripts" -o "$CH_DIR/summaries" -m "$CH_DIR/manifest.json" \
    --backend "$CH_BACKEND" --channel-name "$CH_NAME" ${1:+--only "$1"}
}

drafts() {  # $1: --only filter (optional); needs a voice guide
  [ -f "$CH_DIR/prompts/voice_guide.md" ] || return 0
  (cd "$CH_DIR" && python3 "$ROOT/generate_posts.py" --backend "$CH_BACKEND" \
    ${1:+--only "$1"})
}

publish_site() {  # callers serialize via flock
  local out="$CH_DIR/docs"
  [ -n "$CH_REPO" ] && out="$CH_PUBLISH_DIR/docs"
  python3 "$ROOT/build_site.py" -o "$out" \
    -t "$CH_DIR/transcripts" -p "$CH_DIR/posts" -s "$CH_DIR/summaries" \
    -m "$CH_DIR/manifest.json"
  [ -n "$CH_REPO" ] || return 0
  [ "${NO_PUBLISH:-0}" = "1" ] && { echo "    NO_PUBLISH=1 — skipping git push"; return 0; }
  git -C "$CH_PUBLISH_DIR" add docs
  if ! git -C "$CH_PUBLISH_DIR" diff --cached --quiet; then
    git -C "$CH_PUBLISH_DIR" commit -q -m "site: refresh ($(date '+%Y-%m-%d %H:%M'))"
    git -C "$CH_PUBLISH_DIR" push -q origin HEAD
    echo "    published → $CH_PAGES_URL"
  else
    echo "    no site changes to publish."
  fi
}

postprocess_episode() {  # $1: episode stem — summarize, then publish (locked)
  summarize "$1"
  drafts "$1"
  ( flock 9 && publish_site ) 9>"$PUBLISH_LOCK"
}

echo "==> [1/4] Scrape + download new audio"
before=$(find "$CH_DIR/audio" -name '*.m4a' 2>/dev/null | wc -l)
(cd "$CH_DIR" && python3 "$ROOT/standfm_scrape.py" "$CH_ID" -o audio)
after=$(find "$CH_DIR/audio" -name '*.m4a' 2>/dev/null | wc -l)
echo "    audio files: $before → $after"

if [ -n "$CH_REPO" ] && [ ! -d "$CH_PUBLISH_DIR/.git" ]; then
  echo "    cloning $CH_REPO → $CH_PUBLISH_DIR"
  gh repo clone "$CH_REPO" "$CH_PUBLISH_DIR"
fi
[ -n "$CH_REPO" ] && git -C "$CH_PUBLISH_DIR" pull --rebase --quiet || true

echo "==> [2/4] Pipeline per episode: transcribe → summarize → publish"
pids=()
new=0
while IFS= read -r -d '' f; do
  stem="$(basename "${f%.*}")"
  [ -s "$CH_DIR/transcripts/$stem.txt" ] && continue
  new=$((new + 1))
  "$ROOT/transcribe_all.sh" "$f" "$CH_DIR/transcripts"          # GPU, foreground
  echo "    ↳ post-processing in background: $stem"
  postprocess_episode "$stem" &                                  # CPU/network, bg
  pids+=($!)
done < <(find "$CH_DIR/audio" -type f -name '*.m4a' -print0 | sort -z)
echo "    new episodes transcribed: $new"
fail=0
for pid in "${pids[@]:-}"; do
  [ -n "$pid" ] && { wait "$pid" || fail=1; }
done
[ "$fail" = 1 ] && echo "    (a post-process chain failed — catch-all below retries)" >&2

echo "==> [3/4] Catch-all: summarize/drafts for anything missed"
summarize || echo "    (some summaries failed — will retry next run)" >&2
drafts || true

echo "==> [4/4] Final site build + publish"
( flock 9 && publish_site ) 9>"$PUBLISH_LOCK"
