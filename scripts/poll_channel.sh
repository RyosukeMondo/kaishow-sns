#!/usr/bin/env bash
# Cheap RSS poll, run every few minutes by standfm-poll@<slug>.timer.
#
# Fetch the channel feed, count episodes whose guid isn't in the manifest
# yet, and — only if there's something new — start the heavy sync service
# (download → Whisper → summarize → publish). When the channel is up to
# date this costs a single RSS GET and exits in well under a second, so a
# 3-minute cadence is cheap; the GPU/LLM pipeline only fires on real new
# content.
#
# Missed work that this gate can't see (an episode scraped into the manifest
# but not yet transcribed, or a failed summarize) is caught by the 6-hour
# standfm-sync sweep, whose pipeline is idempotent.
set -eo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$PWD"

[ $# -ge 1 ] || { echo "usage: $0 <channel-slug-or-id>" >&2; exit 2; }
slug="$1"
eval "$(python3 "$ROOT/channels.py" env "$slug")"
[ "$CH_ENABLED" = "1" ] || { echo "channel $CH_SLUG is disabled — skipping."; exit 0; }

new="$(python3 "$ROOT/scripts/feed_check.py" "$slug")"
if [ "${new:-0}" -gt 0 ]; then
  echo "[$(date '+%F %T')] $CH_SLUG: $new new episode(s) → starting sync"
  # --no-block: return at once; the sync (Whisper) runs in its own unit and
  # systemd coalesces a second trigger while one is already active.
  systemctl --user start --no-block "standfm-sync@${CH_SLUG}.service"
else
  echo "[$(date '+%F %T')] $CH_SLUG: up to date"
fi
