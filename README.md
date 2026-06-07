# stand-fm-scrape

Download every episode of a [stand.fm](https://stand.fm) channel and transcribe
it to text (Japanese) with the local faster-whisper setup in `~/repos/whisper`.

Built for **KAISHOWチャンネル**
(`https://stand.fm/channels/68ea666671fa3adc9777a5fb`) but works for any public
channel.

## Quick start

```bash
./run_pipeline.sh                       # default channel
./run_pipeline.sh <channel-url-or-id>   # any other channel
```

This downloads all audio into `audio/` and writes `.txt` + `.srt` transcripts
into `transcripts/`. Both steps are idempotent — re-running skips work already
done, so it's safe to resume after an interruption.

## How the extraction works — light → heavy

The brief was to try the lightest viable method first and escalate only if
needed. **The lightest method won outright**, so the heavier tiers are
documented but unused:

| Tier | Method | Result |
|------|--------|--------|
| 1. **curl + RSS** ✅ | Every public stand.fm channel exposes a podcast feed at `https://stand.fm/rss/<channelId>`. Each `<item>` carries a direct `<enclosure>` audio URL (`cdncf.stand.fm/audios/*.m4a`) — plain HTTP, **no auth, resumable, all episodes in one request**. | **Used.** Fetched 35/35 episodes. |
| 2. HTML scrape | The channel page is a Relay/GraphQL SPA. Episode IDs live in `window.__SERVER_RELAY_STATE__`, but the server-rendered HTML only contains the first ~10 and **no audio URLs** (those need follow-up GraphQL calls). | Not needed. |
| 3. Browser extension / headless | Drive a real browser (CDP), play each episode, capture the media request. Heaviest, needed only if the RSS feed were disabled. | Not needed. |

Because tier 1 covers everything, the scraper is **dependency-free** (Python
stdlib only) and runs anywhere with `curl`.

## Files

- **`standfm_scrape.py`** — fetch the RSS feed, parse episodes, download each
  `.m4a` (resumable via `curl -C -`, skips existing). Writes `manifest.csv` /
  `manifest.json` with title, date, url, and local filename per episode.
  - `python3 standfm_scrape.py <channel> --list` — list episodes, download nothing.
- **`transcribe_all.sh`** — run `~/repos/whisper/transcribe.py` over `audio/`,
  one file at a time, skipping episodes already transcribed. Forces `-l ja` and
  `-m large-v3` (Japanese auto-detect is unreliable on quiet intros).
- **`run_pipeline.sh`** — scrape → transcribe, end to end.

## Output naming

`<YYYY-MM-DD>_<title>.m4a` → `<YYYY-MM-DD>_<title>.txt` / `.srt`, so audio and
its transcript share a stem and sort chronologically. `manifest.json` maps each
file back to its episode metadata.

## Requirements

- `curl`, `python3` (stdlib only) for scraping.
- The `~/repos/whisper` venv (faster-whisper). GPU (CUDA) auto-detected; falls
  back to CPU. Override the whisper location with `WHISPER_DIR=...`.

## Notes

- `audio/`, `transcripts/`, and the manifests are git-ignored — they're
  regenerable from the channel.
- Tested throughput: ~7× realtime on an RTX 3060 with `large-v3` + VAD
  (a 44-min episode ≈ 6 min wall).
