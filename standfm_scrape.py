#!/usr/bin/env python3
"""Download every episode of a stand.fm channel as audio.

stand.fm is a Relay/GraphQL SPA, but every public channel also exposes a
podcast RSS feed at https://stand.fm/rss/<channelId> whose <item> entries
carry a direct, resumable <enclosure> audio URL (cdncf.stand.fm/audios/*.m4a).
That is the lightest possible extraction path — plain HTTP, no auth, no
headless browser — so this is the tool we reach for first.

Output:
  audio/<YYYY-MM-DD>_<slug>.m4a   one file per episode (idempotent, resumable)
  manifest.csv / manifest.json    episode metadata (title, date, url, file)

Dependency-free (stdlib only). Downloads shell out to curl for resume/retry.
"""

import argparse
import csv
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
RSS_TMPL = "https://stand.fm/rss/{channel}"


def resolve_channel_id(arg: str) -> str:
    """Accept a channel id, a channel URL, or an rss URL → return channel id."""
    m = re.search(r"(?:channels/|rss/)([a-f0-9]{16,})", arg)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-f0-9]{16,}", arg):
        return arg
    raise SystemExit(f"Could not parse a channel id from: {arg!r}")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def slugify(title: str, maxlen: int = 60) -> str:
    """Filesystem-safe slug; keeps Japanese, drops path/shell-hostile chars."""
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "", title).strip()
    s = re.sub(r"\s+", "_", s)
    return s[:maxlen] or "untitled"


def parse_feed(xml_bytes: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(xml_bytes)
    chan = root.find("channel")
    if chan is None:
        raise SystemExit("Malformed RSS: no <channel> element")
    channel_title = (chan.findtext("title") or "channel").strip()

    episodes = []
    for item in chan.findall("item"):
        enc = item.find("enclosure")
        url = enc.get("url") if enc is not None else None
        if not url:
            continue
        pub = item.findtext("pubDate")
        try:
            dt = parsedate_to_datetime(pub) if pub else None
            date = dt.strftime("%Y-%m-%d") if dt else "0000-00-00"
        except (TypeError, ValueError):
            date = "0000-00-00"
        title = (item.findtext("title") or "untitled").strip()
        ext = Path(urllib.parse.urlparse(url).path).suffix or ".m4a"
        episodes.append({
            "date": date,
            "title": title,
            "url": url,
            "guid": (item.findtext("guid") or "").strip(),
            "filename": f"{date}_{slugify(title)}{ext}",
        })
    # oldest first → numbered/sorted chronologically
    episodes.sort(key=lambda e: e["date"])
    return channel_title, episodes


def download(url: str, dest: Path) -> bool:
    """Resumable, retrying download via curl. Skip if already complete."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  ✓ skip (exists): {dest.name}")
        return True
    print(f"  ↓ {dest.name}")
    cmd = [
        "curl", "-fL", "--retry", "5", "--retry-delay", "2",
        "-C", "-", "-A", UA, "-o", str(dest), url,
    ]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print(f"  ✗ failed ({r.returncode}): {url}", file=sys.stderr)
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink()
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Download a stand.fm channel's audio")
    ap.add_argument("channel", help="channel id, channel URL, or rss URL")
    ap.add_argument("-o", "--out", default="audio", type=Path,
                    help="audio output dir (default: audio)")
    ap.add_argument("--list", action="store_true",
                    help="list episodes only, do not download")
    args = ap.parse_args()

    cid = resolve_channel_id(args.channel)
    rss_url = RSS_TMPL.format(channel=cid)
    print(f"Channel id : {cid}")
    print(f"RSS feed   : {rss_url}")

    title, episodes = parse_feed(fetch(rss_url))
    print(f"Channel    : {title}")
    print(f"Episodes   : {len(episodes)}\n")

    args.out.mkdir(parents=True, exist_ok=True)
    # write manifest next to audio dir's parent (cwd)
    with open("manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "title", "filename", "url", "guid"])
        w.writeheader()
        w.writerows(episodes)
    Path("manifest.json").write_text(
        json.dumps({"channel": title, "channelId": cid, "episodes": episodes},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if args.list:
        for e in episodes:
            print(f"  {e['date']}  {e['title']}")
        return

    ok = 0
    for e in episodes:
        if download(e["url"], args.out / e["filename"]):
            ok += 1
    print(f"\nDone: {ok}/{len(episodes)} downloaded into {args.out}/")
    print("Manifest: manifest.csv, manifest.json")


if __name__ == "__main__":
    main()
