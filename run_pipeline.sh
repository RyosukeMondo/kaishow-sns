#!/usr/bin/env bash
# End-to-end: scrape a stand.fm channel → download audio → transcribe to text.
#
# Usage:
#   ./run_pipeline.sh                       # default channel (KAISHOWチャンネル)
#   ./run_pipeline.sh <channel-url-or-id>   # any other channel
#
# Idempotent: re-running skips already-downloaded audio and lets whisper
# overwrite/refresh transcripts. Safe to resume after an interruption.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

CHANNEL="${1:-https://stand.fm/channels/68ea666671fa3adc9777a5fb}"

echo "==> [1/2] Scraping + downloading audio"
python3 standfm_scrape.py "$CHANNEL" -o audio

echo
echo "==> [2/2] Transcribing with faster-whisper"
./transcribe_all.sh audio transcripts

echo
echo "==> Done. Audio in audio/, transcripts (.txt/.srt) in transcripts/"
