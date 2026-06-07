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
  `manifest.json` with title, date, **episode page URL**, and local filename.
  - `python3 standfm_scrape.py <channel> --list` — list episodes, download nothing.
- **`transcribe_all.sh`** — run `~/repos/whisper/transcribe.py` over `audio/`,
  one file at a time, skipping episodes already transcribed. Forces `-l ja` and
  `-m large-v3` (Japanese auto-detect is unreliable on quiet intros).
- **`generate_posts.py`** — turn each transcript into a ready-to-post SNS
  teaser (see below).
- **`prompts/voice_guide.md`** — the editable voice/format spec the generator
  uses. **Tune the host's voice here** by pasting his past high-performing posts.
- **`posts/EXAMPLE_*.md`** — hand-written gold-standard post(s), the quality bar.
- **`run_pipeline.sh`** — scrape → transcribe, end to end.

## SNS post generation (`generate_posts.py`)

Implements the client's brief: from an archive episode, produce an **editable
SNS post** that outlines the episode, **withholds the punchline (teaser)**,
sounds like the host, and ends with a link back to the archive.

```bash
python3 generate_posts.py                         # all transcripts → posts/
python3 generate_posts.py --only 251012           # one episode
python3 generate_posts.py --backend claude        # higher quality (vs default claude-minimax)
python3 generate_posts.py --force                 # regenerate existing
```

Each `posts/<episode>.md` contains: an internal 概略, a copy-paste **Facebook**
post, an **Instagram** version with hashtags, and 3 alternate hooks to choose
from. The `{{LINK}}` placeholder is auto-filled with the episode URL.

**Voice tuning is data, not code:** edit `prompts/voice_guide.md` (especially
the "お手本投稿" few-shot slot at the bottom) and re-run with `--force`. The
hand-written `posts/EXAMPLE_*.md` shows the target quality.

> Note: `claude-minimax` (the cheap default, a headless Claude Code session) can
> be slow/flaky on long transcripts. For client-facing copy prefer
> `--backend claude`, or refine the hand-written examples directly.

## Voice matching from Facebook (`extract_voice.py`)

The host's real voice is learned from his **highest-engagement Facebook posts**,
pulled from the `facebook-scraper` SQLite DB:

```bash
python3 extract_voice.py --profile santa.kinoshita --min-reactions 70 --top 12
```

This writes `prompts/fb_samples.md` (his top posts as few-shot), which
`generate_posts.py` automatically appends to every prompt.

> **Privacy:** `prompts/fb_samples.md` holds his *personal* FB posts and is
> **git-ignored — never published.** Only the generated promo copy goes public.

## End-to-end auto-pipeline (`sync.sh`)

Detect new episodes → download → transcribe → refresh voice → generate drafts →
rebuild site → publish. Every stage is idempotent, so it's safe on a schedule.

```bash
./sync.sh                     # default channel: full run + publish to Pages
NO_PUBLISH=1 ./sync.sh        # build everything locally, don't push
```

Run it on a timer (e.g. cron, hourly) to auto-publish new episodes:

```cron
0 * * * * cd /home/rmondo/repos/stand-fm-scrape && flock -n .sync.lock ./sync.sh >> sync.log 2>&1
```

## Published site (`build_site.py` → GitHub Pages)

`build_site.py` renders `docs/` (served by Pages from `/docs`): an episode
index plus a per-episode page with the summary, **copy-paste FB & IG boxes
(with copy buttons)**, hooks, and the full transcript. `<meta noindex>` keeps it
out of search results. The host opens an episode, hits コピー, pastes into Facebook.

First-time publish:

```bash
gh repo create kaishow-sns --public --source=. --remote=origin
python3 build_site.py
git add -A && git commit -m "init"
git push -u origin main
gh api -X POST repos/:owner/kaishow-sns/pages -f 'source[branch]=main' -f 'source[path]=/docs'
# site: https://<user>.github.io/kaishow-sns/
```

After that, `./sync.sh` keeps it current automatically.

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
