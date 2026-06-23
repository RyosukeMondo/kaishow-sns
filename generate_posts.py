#!/usr/bin/env python3
"""Turn episode transcripts into ready-to-post SNS teasers (KAISHOW's voice).

Implements the client's brief from the interview: paste an archive link →
get an editable SNS post that outlines the episode, withholds the punchline
(teaser), sounds like the host, and ends with a link back to the archive.

For each transcript it builds a prompt from prompts/voice_guide.md + the
episode metadata (title/date/link from manifest.json) + the transcript, sends
it to a headless LLM CLI, and writes posts/<stem>.md. The {{LINK}} placeholder
the model emits is replaced with the real episode URL.

Voice tuning lives entirely in prompts/voice_guide.md (paste the client's
past high-performing posts there) — no code change needed.

Idempotent: skips episodes whose post already exists (use --force to redo).
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

GUIDE = Path("prompts/voice_guide.md")
SAMPLES = Path("prompts/fb_samples.md")  # auto-extracted FB voice few-shot (local only)

# The host writes SNS copy in the first person "私" (the voice guide asks for it,
# but an LLM still slips into the spoken "僕"/"俺" sometimes). Normalize the
# generated copy so the published draft is always "私". 僕→私 / 俺→私 are clean
# pronoun swaps; the negative lookbehind protects the rare 公僕/下僕/従僕 compounds.
_FIRST_PERSON_RE = re.compile(r"(?<![公下従])[僕俺]")


def normalize_first_person(text: str) -> str:
    """Force the host's first-person pronoun to 「私」 in generated SNS copy."""
    return _FIRST_PERSON_RE.sub("私", text)


def load_manifest() -> dict:
    if not Path("manifest.json").exists():
        sys.exit("manifest.json not found — run standfm_scrape.py first.")
    return json.loads(Path("manifest.json").read_text(encoding="utf-8"))


def build_prompt(guide: str, ep: dict, transcript: str) -> str:
    return (
        f"{guide}\n\n"
        "----- 対象エピソードのメタ情報 -----\n"
        f"タイトル: {ep['title']}\n"
        f"配信日: {ep['date']}\n"
        f"アーカイブURL: {ep.get('page') or ep.get('guid') or ''}\n\n"
        "----- 文字起こしここから -----\n\n"
        f"{transcript}\n"
    )


def run_llm(prompt: str, backend: str) -> str:
    """Send prompt on stdin to the headless CLI (claude-minimax / claude -p)."""
    r = subprocess.run([backend, "-p"], input=prompt,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{backend} failed: {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate SNS teaser posts from transcripts")
    ap.add_argument("-t", "--transcripts", default="transcripts", type=Path)
    ap.add_argument("-o", "--out", default="posts", type=Path)
    ap.add_argument("--backend", default="claude-minimax",
                    help="LLM CLI: claude-minimax (default, cheap) or claude (higher quality)")
    ap.add_argument("--force", action="store_true", help="regenerate even if post exists")
    ap.add_argument("--only", default=None,
                    help="substring filter: only episodes whose filename matches")
    args = ap.parse_args()

    if not GUIDE.exists():
        sys.exit(f"voice guide not found: {GUIDE}")
    guide = GUIDE.read_text(encoding="utf-8")
    if SAMPLES.exists():
        guide += "\n\n" + SAMPLES.read_text(encoding="utf-8")
        print(f"  (voice few-shot: {SAMPLES})")
    manifest = load_manifest()
    args.out.mkdir(parents=True, exist_ok=True)

    # map transcript stem -> episode metadata
    by_stem = {Path(e["filename"]).stem: e for e in manifest["episodes"]}

    txts = sorted(p for p in args.transcripts.glob("*.txt"))
    if args.only:
        txts = [p for p in txts if args.only in p.name]
    if not txts:
        sys.exit(f"no transcripts found in {args.transcripts}/")

    ok = 0
    for txt in txts:
        stem = txt.stem
        out = args.out / f"{stem}.md"
        if out.exists() and not args.force:
            print(f"  ✓ skip (exists): {stem}")
            ok += 1
            continue
        ep = by_stem.get(stem, {"title": stem, "date": "", "page": ""})
        link = ep.get("page") or ep.get("guid") or ""
        print(f"  ✍  {stem}")
        try:
            result = run_llm(build_prompt(guide, ep, txt.read_text(encoding="utf-8")),
                             args.backend)
        except RuntimeError as exc:
            print(f"  ✗ {exc}", file=sys.stderr)
            continue
        if not result:
            print(f"  ✗ empty result for {stem}", file=sys.stderr)
            continue
        result = normalize_first_person(result.replace("{{LINK}}", link))
        out.write_text(result + "\n", encoding="utf-8")
        ok += 1

    print(f"\nDone: {ok}/{len(txts)} posts in {args.out}/")


if __name__ == "__main__":
    main()
