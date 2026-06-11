#!/usr/bin/env bash
# Per-channel pipeline: detect new stand.fm episodes → download → transcribe →
# summarize → (SNS drafts if the channel has a voice guide) → build site →
# publish to the channel's own GitHub Pages repo.
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

mkdir -p "$CH_DIR"

echo "==> [1/5] Scrape + download new audio"
before=$(find "$CH_DIR/audio" -name '*.m4a' 2>/dev/null | wc -l)
(cd "$CH_DIR" && python3 "$ROOT/standfm_scrape.py" "$CH_ID" -o audio)
after=$(find "$CH_DIR/audio" -name '*.m4a' 2>/dev/null | wc -l)
echo "    audio files: $before → $after"

echo "==> [2/5] Transcribe new episodes"
"$ROOT/transcribe_all.sh" "$CH_DIR/audio" "$CH_DIR/transcripts"

echo "==> [3/5] Summarize new episodes (backend: $CH_BACKEND)"
python3 "$ROOT/summarize_episodes.py" \
  -t "$CH_DIR/transcripts" -o "$CH_DIR/summaries" -m "$CH_DIR/manifest.json" \
  --backend "$CH_BACKEND" --channel-name "$CH_NAME"

echo "==> [4/5] SNS drafts (only if the channel has a voice guide)"
if [ -f "$CH_DIR/prompts/voice_guide.md" ]; then
  (cd "$CH_DIR" && python3 "$ROOT/generate_posts.py" --backend "$CH_BACKEND")
else
  echo "    (no $CH_DIR/prompts/voice_guide.md — skipping drafts)"
fi

echo "==> [5/5] Build + publish site"
if [ -z "$CH_REPO" ]; then
  echo "    no publish repo configured for $CH_SLUG — building locally only."
  python3 "$ROOT/build_site.py" -o "$CH_DIR/docs" \
    -t "$CH_DIR/transcripts" -p "$CH_DIR/posts" -s "$CH_DIR/summaries" \
    -m "$CH_DIR/manifest.json"
  exit 0
fi

if [ ! -d "$CH_PUBLISH_DIR/.git" ]; then
  echo "    cloning $CH_REPO → $CH_PUBLISH_DIR"
  gh repo clone "$CH_REPO" "$CH_PUBLISH_DIR"
fi
git -C "$CH_PUBLISH_DIR" pull --rebase --quiet || true

python3 "$ROOT/build_site.py" -o "$CH_PUBLISH_DIR/docs" \
  -t "$CH_DIR/transcripts" -p "$CH_DIR/posts" -s "$CH_DIR/summaries" \
  -m "$CH_DIR/manifest.json"

if [ "${NO_PUBLISH:-0}" = "1" ]; then
  echo "    NO_PUBLISH=1 — skipping git push"
  exit 0
fi

cd "$CH_PUBLISH_DIR"
git add docs
if ! git diff --cached --quiet; then
  git commit -m "site: refresh ($(date '+%Y-%m-%d %H:%M'))"
  git push origin "$(git rev-parse --abbrev-ref HEAD)"
  echo "    published → $CH_PAGES_URL"
else
  echo "    no site changes to publish."
fi
