#!/usr/bin/env python3
"""Tests for scripts/feed_check.py — the new-episode gate behind the poller.

These run with no network: STANDFM_CHANNELS points channels.load() at a temp
registry, and standfm_scrape.load_episodes is stubbed to return a canned feed.

    python3 tests/test_feed_check.py        # self-contained runner
    python3 -m pytest tests/test_feed_check.py   # if pytest is available
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_CID = "feedchecktest00000f"


def _write_registry(tmp_path: Path, slug: str) -> Path:
    (tmp_path / "channels.json").write_text(
        json.dumps({"channels": [{"id": _CID, "slug": slug, "name": "TC"}]}),
        encoding="utf-8",
    )
    return tmp_path / "channels.json"


def _stub_feed(feed_guids: list[str]):
    """Point feed_check's load_episodes at a canned episode list."""
    import standfm_scrape
    standfm_scrape.load_episodes = lambda _cid, _rss: ("TC", [{"guid": g} for g in feed_guids])


def test_no_new_when_manifest_matches_feed(tmp_path: Path) -> None:
    (tmp_path / "channels" / _CID).mkdir(parents=True)
    (tmp_path / "channels" / _CID / "manifest.json").write_text(
        json.dumps({"channel": "TC", "channelId": _CID,
                    "episodes": [{"guid": "a"}, {"guid": "b"}]}),
        encoding="utf-8",
    )
    os.environ["STANDFM_CHANNELS"] = str(_write_registry(tmp_path, "tc"))
    _stub_feed(["a", "b"])
    import feed_check
    assert feed_check.new_episode_count("tc") == 0


def test_counts_only_unknown_guids(tmp_path: Path) -> None:
    (tmp_path / "channels" / _CID).mkdir(parents=True)
    (tmp_path / "channels" / _CID / "manifest.json").write_text(
        json.dumps({"channel": "TC", "channelId": _CID, "episodes": [{"guid": "a"}]}),
        encoding="utf-8",
    )
    os.environ["STANDFM_CHANNELS"] = str(_write_registry(tmp_path, "tc"))
    _stub_feed(["a", "b", "c"])  # b and c are new
    import feed_check
    assert feed_check.new_episode_count("tc") == 2


def test_brand_new_channel_has_no_manifest(tmp_path: Path) -> None:
    # No manifest.json at all → every feed episode counts as new.
    (tmp_path / "channels" / _CID).mkdir(parents=True)
    os.environ["STANDFM_CHANNELS"] = str(_write_registry(tmp_path, "tc"))
    _stub_feed(["a", "b"])
    import feed_check
    assert feed_check.new_episode_count("tc") == 2


def test_corrupt_manifest_treated_as_empty(tmp_path: Path) -> None:
    (tmp_path / "channels" / _CID).mkdir(parents=True)
    (tmp_path / "channels" / _CID / "manifest.json").write_text("{not json", encoding="utf-8")
    os.environ["STANDFM_CHANNELS"] = str(_write_registry(tmp_path, "tc"))
    _stub_feed(["a"])
    import feed_check
    assert feed_check.new_episode_count("tc") == 1


def test_resolves_by_slug_or_id(tmp_path: Path) -> None:
    (tmp_path / "channels" / _CID).mkdir(parents=True)
    (tmp_path / "channels" / _CID / "manifest.json").write_text(
        json.dumps({"channel": "TC", "channelId": _CID, "episodes": [{"guid": "a"}]}),
        encoding="utf-8",
    )
    os.environ["STANDFM_CHANNELS"] = str(_write_registry(tmp_path, "tc"))
    _stub_feed(["a", "b"])
    import feed_check
    assert feed_check.new_episode_count("tc") == 1      # by slug
    assert feed_check.new_episode_count(_CID) == 1       # by id


def _main() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_"):
            continue
        with tempfile.TemporaryDirectory() as td:
            try:
                fn(Path(td))
            except AssertionError as e:
                fails += 1
                print(f"FAIL {name}: {e}")
            else:
                print(f"ok   {name}")
    print(f"\n{'FAILURES' if fails else 'all passed'}: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_main())
