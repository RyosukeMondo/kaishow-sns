#!/usr/bin/env python3
"""Summarize each transcribed episode with a headless LLM CLI.

For every transcript in --transcripts missing a summaries/<stem>.md, pipe a
Japanese summarization prompt to the backend CLI (`<backend> -p` on stdin —
same contract as generate_posts.py) and write the result.

Idempotent: existing summaries are skipped unless --force.
"""

import argparse
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

PROMPT_TMPL = (
    "以下はstand.fmの音声配信「{channel}」のエピソード「{title}」"
    "（{date}）の文字起こしです。日本語で要約してください：\n"
    "(1) 全体の要約を3〜5文（## 📝 要約 の見出しで）、\n"
    "(2) 主なトピックを箇条書き（## 📌 トピック の見出しで）、\n"
    "(3) 印象的な発言を1〜2個引用（## 💬 印象的な発言 の見出しで）。\n"
    "出力はMarkdownのみ。前置き・後書きは不要です。\n\n"
    "----- 文字起こしここから -----\n\n"
    "{transcript}\n"
)


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def run_llm(prompt: str, backend: str) -> str:
    """Send prompt on stdin to the headless CLI (claude-minimax / claude -p)."""
    r = subprocess.run([backend, "-p"], input=prompt,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{backend} failed: {r.stderr.strip()[:500]}")
    return r.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize episode transcripts")
    ap.add_argument("-t", "--transcripts", default="transcripts", type=Path)
    ap.add_argument("-o", "--out", default="summaries", type=Path)
    ap.add_argument("-m", "--manifest", default="manifest.json", type=Path)
    ap.add_argument("--backend", default="claude-minimax",
                    help="LLM CLI: claude-minimax (default, cheap) or claude")
    ap.add_argument("--channel-name", default=None,
                    help="channel display name for the prompt (default: from manifest)")
    ap.add_argument("--force", action="store_true", help="regenerate even if summary exists")
    ap.add_argument("--only", default=None,
                    help="substring filter: only episodes whose filename matches")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    channel = args.channel_name or manifest.get("channel", "channel")
    by_stem = {nfc(Path(e["filename"]).stem): e for e in manifest["episodes"]}

    txts = sorted(args.transcripts.glob("*.txt"))
    if args.only:
        txts = [p for p in txts if args.only in p.name]
    if not txts:
        sys.exit(f"no transcripts found in {args.transcripts}/")

    args.out.mkdir(parents=True, exist_ok=True)
    ok = failed = 0
    for txt in txts:
        stem = nfc(txt.stem)
        out = args.out / f"{stem}.md"
        if out.exists() and not args.force:
            print(f"  ✓ skip (exists): {stem}")
            ok += 1
            continue
        ep = by_stem.get(stem, {"title": stem, "date": ""})
        print(f"  ✍  {stem}")
        prompt = PROMPT_TMPL.format(channel=channel, title=ep["title"],
                                    date=ep["date"],
                                    transcript=txt.read_text(encoding="utf-8"))
        try:
            out.write_text(run_llm(prompt, args.backend) + "\n", encoding="utf-8")
            ok += 1
        except RuntimeError as exc:
            print(f"  ✗ {stem}: {exc}", file=sys.stderr)
            failed += 1

    print(f"Summaries: {ok} ok, {failed} failed → {args.out}/")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
