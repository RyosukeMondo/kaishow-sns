#!/usr/bin/env python3
"""Build the voice few-shot file from the host's high-performing Facebook posts.

Reads the facebook-scraper SQLite DB (~/repos/facebook-scraper/data/facebook.db),
picks the top posts by reactions (the ones that actually landed), and writes them
to prompts/fb_samples.md. generate_posts.py appends this file to every prompt so
the generated copy matches his real FB voice.

PRIVACY: fb_samples.md contains his personal posts — it is git-ignored and never
published. Only the generated promo copy is meant to go public.
"""

import argparse
import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / "repos/facebook-scraper/data/facebook.db"
OUT = Path("prompts/fb_samples.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract FB voice samples")
    ap.add_argument("--db", default=DEFAULT_DB, type=Path)
    ap.add_argument("--profile", default=None, help="filter to one profile")
    ap.add_argument("--min-reactions", type=int, default=70)
    ap.add_argument("--top", type=int, default=12, help="how many posts to include")
    ap.add_argument("--min-len", type=int, default=120, help="skip short posts (chars)")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(f"FB DB not found: {args.db}")

    con = sqlite3.connect(str(args.db))
    q = ("SELECT message, reactions, comments FROM posts "
         "WHERE message IS NOT NULL AND length(message) >= ? AND reactions >= ?")
    params: list = [args.min_len, args.min_reactions]
    if args.profile:
        q += " AND profile = ?"
        params.append(args.profile)
    q += " ORDER BY reactions DESC LIMIT ?"
    params.append(args.top)
    rows = con.execute(q, params).fetchall()
    if not rows:
        raise SystemExit("No matching posts — lower --min-reactions/--min-len?")

    parts = [
        "# お手本投稿（Facebook 反響上位・自動抽出）",
        "",
        "> facebook-scraper のDBから反響（リアクション）上位を自動抽出したもの。",
        "> generate_posts.py がプロンプト末尾に連結し、本人の語彙・改行・テンションを学習します。",
        "> ⚠️ 本人の個人投稿のため git 管理外。公開しないこと。",
        "",
    ]
    for i, (msg, rx, cm) in enumerate(rows, 1):
        parts.append(f"### お手本{i}（リアクション{rx}件 / コメント{cm}件）")
        parts.append("")
        parts.append(msg.strip())
        parts.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {len(rows)} samples → {OUT} "
          f"(reactions {rows[-1][1]}–{rows[0][1]})")


if __name__ == "__main__":
    main()
