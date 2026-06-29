#!/usr/bin/env python3
"""Cheap new-episode check for the 3-minute poller.

Fetches the channel feed (RSS, with the page-scrape fallback) and counts
episodes whose ``guid`` is absent from the manifest. Prints that count as a
single integer on stdout and exits 0. ``scripts/poll_channel.sh`` uses it to
decide whether to start the heavy sync service.

Stays deliberately light: one RSS GET + a manifest read. No audio download,
no Whisper, no LLM — that is what makes polling every few minutes affordable.
The full processing pipeline lives in ``standfm-sync@<slug>.service``.

Note: once an episode is scraped into the manifest its guid is "known", so a
crash between scrape and transcribe won't be re-detected here. The 6-hour
sync sweep covers that gap — its pipeline is idempotent and transcribes any
audio whose .txt is still missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# This helper lives in scripts/ but imports channels/standfm_scrape from the
# repo root; put the root on sys.path so it resolves regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import channels as chan  # noqa: E402
import standfm_scrape  # noqa: E402


def new_episode_count(slug_or_id: str) -> int:
    """Number of feed episodes whose guid is not yet in the manifest."""
    reg = chan.load()
    c = reg.require(slug_or_id)
    try:
        known = {
            e.get("guid")
            for e in json.loads(c.manifest_path.read_text(encoding="utf-8")).get("episodes", [])
        }
    except (FileNotFoundError, ValueError):
        known = set()
    # load_episodes returns (channel_title, episodes); we only need the guids.
    episodes = standfm_scrape.load_episodes(c.id, c.rss_url)[1]
    return sum(1 for e in episodes if e.get("guid") not in known)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: feed_check.py <channel-slug-or-id>", file=sys.stderr)
        return 2
    print(new_episode_count(argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
