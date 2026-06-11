#!/usr/bin/env python3
"""Channel registry + path resolver — the single source of truth for the
multi-channel layout. Every pipeline stage (scrape → stt → generate → build →
publish) and the ``channelctl`` CLI import this module instead of hardcoding
paths in the current working directory.

Layout (base = the directory containing channels.json; override the whole tree
for tests via the ``STANDFM_CHANNELS`` env var pointing at an alternate
registry file):

    channels.json                         the registry (input to this module)
    channels/<id>/audio/                  downloaded .m4a (gitignored)
    channels/<id>/transcripts/            .txt/.srt        (gitignored)
    channels/<id>/posts/                  generated <stem>.md (gitignored)
    channels/<id>/manifest.json|.csv      episode metadata (gitignored)
    channels/<id>/prompts/voice_guide.md  per-channel voice spec (tracked)
    channels/<id>/prompts/fb_samples.md   FB few-shot       (gitignored)
    channels/<id>/.state.json             runtime state: last_run, counts
    .publish/<repo-name>/docs/            clone of the channel's Pages repo

A channel publishes to its own GitHub repo (``owner/name``); the persistent
local clone lives at ``.publish/<name>/`` and is served by Pages from /docs.

Dependency-free (stdlib only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

RSS_TMPL = "https://stand.fm/rss/{channel}"
CHANNEL_TMPL = "https://stand.fm/channels/{channel}"

# A stand.fm channel/episode id is a 16+ hex string; accept id, channel URL,
# or rss URL. Canonical home for this regex — standfm_scrape imports it.
_ID_RE = re.compile(r"(?:channels/|rss/)([a-f0-9]{16,})")


def resolve_channel_id(arg: str) -> str:
    """Accept a channel id, a channel URL, or an rss URL → return the id."""
    m = _ID_RE.search(arg)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-f0-9]{16,}", arg):
        return arg
    raise ValueError(f"Could not parse a channel id from: {arg!r}")


def registry_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the registry file path: explicit arg > $STANDFM_CHANNELS >
    channels.json next to this module."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("STANDFM_CHANNELS")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "channels.json"


class Channel:
    """One registry entry plus every per-channel path derived from it."""

    def __init__(self, data: dict, base_dir: Path):
        self._d = data
        self.base_dir = base_dir

    # --- registry fields (with safe defaults) ---
    @property
    def id(self) -> str:
        return self._d["id"]

    @property
    def slug(self) -> str:
        return self._d.get("slug") or self.id

    @property
    def name(self) -> str:
        return self._d.get("name") or self.slug

    @property
    def enabled(self) -> bool:
        return bool(self._d.get("enabled", True))

    @property
    def repo(self) -> str:
        """GitHub publish repo as ``owner/name`` (may be empty until provisioned)."""
        return self._d.get("repo", "")

    @property
    def backend(self) -> str:
        return self._d.get("backend") or "claude"

    @property
    def fb_profile(self) -> str:
        return self._d.get("fb_profile") or ""

    # --- derived working paths ---
    @property
    def dir(self) -> Path:
        return self.base_dir / "channels" / self.id

    @property
    def audio_dir(self) -> Path:
        return self.dir / "audio"

    @property
    def transcripts_dir(self) -> Path:
        return self.dir / "transcripts"

    @property
    def posts_dir(self) -> Path:
        return self.dir / "posts"

    @property
    def prompts_dir(self) -> Path:
        return self.dir / "prompts"

    @property
    def voice_guide(self) -> Path:
        return self.prompts_dir / "voice_guide.md"

    @property
    def fb_samples(self) -> Path:
        return self.prompts_dir / "fb_samples.md"

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def manifest_csv(self) -> Path:
        return self.dir / "manifest.csv"

    @property
    def state_path(self) -> Path:
        return self.dir / ".state.json"

    # --- publish (per-channel Pages repo clone) ---
    @property
    def repo_owner(self) -> str:
        return self.repo.split("/")[0] if "/" in self.repo else ""

    @property
    def repo_name(self) -> str:
        return self.repo.split("/")[-1] if self.repo else self.slug

    @property
    def publish_dir(self) -> Path:
        return self.base_dir / ".publish" / self.repo_name

    @property
    def publish_docs_dir(self) -> Path:
        return self.publish_dir / "docs"

    @property
    def rss_url(self) -> str:
        return RSS_TMPL.format(channel=self.id)

    @property
    def channel_url(self) -> str:
        return CHANNEL_TMPL.format(channel=self.id)

    @property
    def pages_url(self) -> str:
        if self.repo_owner and self.repo_name:
            return f"https://{self.repo_owner}.github.io/{self.repo_name}/"
        return ""

    # --- runtime state ---
    def load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def save_state(self, **updates) -> None:
        state = self.load_state()
        state.update(updates)
        self.dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.state_path, json.dumps(state, ensure_ascii=False, indent=2))

    def as_dict(self) -> dict:
        return dict(self._d)


class Registry:
    """The whole channels.json, plus the base directory paths resolve against."""

    def __init__(self, data: dict, path: Path):
        self.path = path
        self.base_dir = path.resolve().parent
        self._data = data
        self._channels = [Channel(c, self.base_dir) for c in data.get("channels", [])]

    def all(self) -> list[Channel]:
        return list(self._channels)

    def enabled(self) -> list[Channel]:
        return [c for c in self._channels if c.enabled]

    def get(self, id_or_slug: str) -> Channel | None:
        for c in self._channels:
            if c.id == id_or_slug or c.slug == id_or_slug:
                return c
        # tolerate a URL / partial id
        try:
            cid = resolve_channel_id(id_or_slug)
        except ValueError:
            return None
        for c in self._channels:
            if c.id == cid:
                return c
        return None

    def require(self, id_or_slug: str) -> Channel:
        c = self.get(id_or_slug)
        if c is None:
            raise SystemExit(f"channel not found in registry: {id_or_slug!r}")
        return c

    # --- mutations (persist atomically) ---
    def add(self, entry: dict) -> Channel:
        if self.get(entry["id"]) is not None:
            return self.require(entry["id"])
        self._data.setdefault("channels", []).append(entry)
        self._channels.append(Channel(entry, self.base_dir))
        self.save()
        return self.require(entry["id"])

    def set_enabled(self, id_or_slug: str, enabled: bool) -> Channel:
        c = self.require(id_or_slug)
        c._d["enabled"] = enabled
        self.save()
        return c

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self._data, ensure_ascii=False, indent=2) + "\n")


def load(path: str | os.PathLike[str] | None = None) -> Registry:
    rp = registry_path(path)
    if not rp.exists():
        return Registry({"channels": []}, rp)
    data = json.loads(rp.read_text(encoding="utf-8"))
    return Registry(data, rp)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _count(glob_dir: Path, pattern: str) -> int:
    return len(list(glob_dir.glob(pattern))) if glob_dir.exists() else 0


def channel_status(c: Channel) -> dict:
    """Cheap, network-free status snapshot for `list`/`status`."""
    episodes = 0
    if c.manifest_path.exists():
        try:
            episodes = len(json.loads(c.manifest_path.read_text(encoding="utf-8")).get("episodes", []))
        except ValueError:
            episodes = 0
    return {
        "id": c.id,
        "slug": c.slug,
        "name": c.name,
        "enabled": c.enabled,
        "repo": c.repo,
        "pages_url": c.pages_url,
        "episodes": episodes,
        "transcribed": _count(c.transcripts_dir, "*.txt"),
        "drafts": _count(c.posts_dir, "*.md"),
        "last_run": c.load_state().get("last_run", ""),
    }


def format_table(channels: list[Channel]) -> str:
    rows = [channel_status(c) for c in channels]
    head = f"{'on':2}  {'slug':14}  {'eps':>3} {'txt':>3} {'drf':>3}  {'name':24}  pages"
    lines = [head, "-" * len(head)]
    for r in rows:
        on = "● " if r["enabled"] else "○ "
        lines.append(
            f"{on}  {r['slug'][:14]:14}  {r['episodes']:>3} {r['transcribed']:>3} "
            f"{r['drafts']:>3}  {r['name'][:24]:24}  {r['pages_url']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspect the stand.fm channel registry")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list", help="print the channel table (default)")
    args = ap.parse_args(argv)
    reg = load()
    if args.cmd in (None, "list"):
        print(format_table(reg.all()))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
