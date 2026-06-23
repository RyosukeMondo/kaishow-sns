#!/usr/bin/env python3
"""Backfill: rewrite already-generated SNS drafts to first-person 「私」.

New drafts are normalized at generation time (generate_posts.normalize_first_person).
This applies the *same* function to existing posts/<stem>.md across every channel
in the registry, so past episodes match the host's SNS convention too.

Idempotent — running twice changes nothing. EXAMPLE_*.md (hand-written gold
samples) are left untouched.

    python3 scripts/normalize_posts.py            # all channels
    python3 scripts/normalize_posts.py kaishow    # one channel (slug/id/URL)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import channels  # noqa: E402
from generate_posts import normalize_first_person  # noqa: E402


def normalize_channel(c: channels.Channel) -> tuple[int, int]:
    changed = scanned = 0
    if not c.posts_dir.exists():
        return 0, 0
    for md in sorted(c.posts_dir.glob("*.md")):
        if md.name.startswith("EXAMPLE_"):
            continue
        scanned += 1
        original = md.read_text(encoding="utf-8")
        fixed = normalize_first_person(original)
        if fixed != original:
            md.write_text(fixed, encoding="utf-8")
            changed += 1
            print(f"  ✍  {c.slug}: {md.name}")
    return scanned, changed


def main() -> int:
    reg = channels.load()
    targets = [reg.require(sys.argv[1])] if len(sys.argv) > 1 else reg.all()
    total_scanned = total_changed = 0
    for c in targets:
        scanned, changed = normalize_channel(c)
        total_scanned += scanned
        total_changed += changed
    print(f"Normalized first-person 僕/俺→私: "
          f"{total_changed} file(s) rewritten, {total_scanned} scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
