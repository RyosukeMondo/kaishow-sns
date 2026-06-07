#!/usr/bin/env bash
# Full pipeline: detect new stand.fm episodes → download → transcribe →
# refresh voice → generate FB/IG drafts → rebuild site → publish to Pages.
#
# Every stage is idempotent (skips work already done), so this is safe to run
# on a schedule. New episodes flow straight through to the published site.
#
# Usage:
#   ./sync.sh                         # default channel, publish
#   ./sync.sh <channel-url-or-id>     # another channel
#   NO_PUBLISH=1 ./sync.sh            # build everything but don't git push
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CHANNEL="${1:-https://stand.fm/channels/68ea666671fa3adc9777a5fb}"
BACKEND="${BACKEND:-claude}"
FB_DB="${FB_DB:-$HOME/repos/facebook-scraper/data/facebook.db}"

echo "==> [1/5] Scrape + download new audio"
before=$(find audio -name '*.m4a' 2>/dev/null | wc -l)
python3 standfm_scrape.py "$CHANNEL" -o audio
after=$(find audio -name '*.m4a' 2>/dev/null | wc -l)
echo "    audio files: $before → $after"

echo "==> [2/5] Transcribe new episodes"
./transcribe_all.sh audio transcripts

echo "==> [3/5] Refresh voice few-shot from Facebook (if DB present)"
if [ -f "$FB_DB" ]; then
  python3 extract_voice.py --db "$FB_DB" --profile "${FB_PROFILE:-santa.kinoshita}" || true
else
  echo "    (no FB DB at $FB_DB — skipping; uses voice_guide.md only)"
fi

echo "==> [4/5] Generate FB/IG drafts for new episodes"
python3 generate_posts.py --backend "$BACKEND"

echo "==> [5/5] Build site"
python3 build_site.py

if [ "${NO_PUBLISH:-0}" = "1" ]; then
  echo "==> NO_PUBLISH=1 — skipping git push"
  exit 0
fi

if git remote get-url origin >/dev/null 2>&1; then
  echo "==> Publishing to GitHub Pages"
  git add docs
  if ! git diff --cached --quiet; then
    git commit -m "site: refresh SNS drafts ($(date +%Y-%m-%d))"
    git push origin "$(git rev-parse --abbrev-ref HEAD)"
    echo "    pushed."
  else
    echo "    no site changes to publish."
  fi
else
  echo "==> no git remote 'origin' — run: gh repo create && git push (see README)"
fi
