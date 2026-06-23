#!/usr/bin/env python3
"""Build the GitHub Pages site from manifest + transcripts + generated posts.

Produces docs/ (served by GitHub Pages from /docs):
  docs/index.html        episode list (newest first)
  docs/ep/<id>.html      per-episode: summary, copy-paste FB & IG posts
                         (with copy buttons), hooks, full transcript

The site is a copy-paste dashboard for the host: open an episode, hit "コピー",
paste into Facebook. <meta noindex> keeps it out of search results.
"""

import argparse
import html
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

CSS = """
:root{--bg:#0f1115;--card:#1a1d24;--fg:#e8eaed;--muted:#9aa0a6;--accent:#4f8cff;--ok:#2ea043}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,"Hiragino Kaku Gothic ProN",Meiryo,sans-serif;
background:var(--bg);color:var(--fg);line-height:1.7}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{padding:24px 16px;border-bottom:1px solid #2a2e37}
.wrap{max-width:820px;margin:0 auto;padding:16px}
h1{font-size:1.4rem;margin:.2em 0}
.muted{color:var(--muted);font-size:.9rem}
.card{background:var(--card);border:1px solid #2a2e37;border-radius:12px;padding:16px;margin:14px 0}
.card h2{font-size:1.05rem;margin:.2em 0}
.ep-list a.title{font-weight:600}
.badge{display:inline-block;background:#2a2e37;border-radius:6px;padding:2px 8px;font-size:.78rem;color:var(--muted);margin-right:6px}
.copybox{position:relative;margin:10px 0}
.copybox textarea{width:100%;min-height:200px;background:#0c0e12;color:var(--fg);border:1px solid #2a2e37;
border-radius:8px;padding:12px;font:inherit;resize:vertical}
.copybtn{position:absolute;top:8px;right:8px;background:var(--accent);color:#fff;border:0;border-radius:8px;
padding:8px 14px;font-weight:600;cursor:pointer}
.copybtn.done{background:var(--ok)}
details{margin-top:10px}summary{cursor:pointer;color:var(--muted)}
.transcript{white-space:pre-wrap;background:#0c0e12;border:1px solid #2a2e37;border-radius:8px;padding:12px;
max-height:60vh;overflow:auto;font-size:.92rem}
.btnrow{margin:10px 0}.btnrow a{display:inline-block;background:#2a2e37;border-radius:8px;padding:8px 14px;margin-right:8px}
footer{padding:24px 16px;color:var(--muted);font-size:.82rem;text-align:center}
.pending{color:var(--muted);font-style:italic}
.bar{background:#0c0e12;border:1px solid #2a2e37;border-radius:999px;height:14px;overflow:hidden;margin:6px 0}
.bar-fill{background:linear-gradient(90deg,#2ea043,#4f8cff);height:100%;border-radius:999px;transition:width .4s}
.ep-list .card{display:flex;align-items:flex-start;gap:12px}
.posted{display:flex;align-items:center;gap:6px;flex:0 0 auto;color:var(--muted);font-size:.82rem;
white-space:nowrap;cursor:pointer;user-select:none;padding-top:2px}
.posted input{width:18px;height:18px;accent-color:var(--ok);cursor:pointer;margin:0}
.ep-main{flex:1 1 auto;min-width:0}
.card.done{opacity:.55}
.card.done .title{text-decoration:line-through;color:var(--muted)}
.card.done .posted{color:var(--ok)}
"""

COPY_JS = """
function copyEl(id,btn){const t=document.getElementById(id);t.select();
navigator.clipboard.writeText(t.value).then(()=>{const o=btn.textContent;btn.textContent='コピーしました ✓';
btn.classList.add('done');setTimeout(()=>{btn.textContent=o;btn.classList.remove('done')},1500)})}
"""

# "投稿済み" checkboxes persist in the host's browser via localStorage. Both
# channels' Pages sites share the github.io origin, so the key is namespaced per
# channel (KEY placeholder filled at build time) to keep their state separate.
POSTED_JS = """
(function(){var KEY=%s;
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
function save(p){localStorage.setItem(KEY,JSON.stringify(p))}
function count(){var n=Object.keys(load()).length;var el=document.getElementById('posted-count');
if(el)el.textContent=n}
document.addEventListener('DOMContentLoaded',function(){var p=load();
document.querySelectorAll('.ep-list .card').forEach(function(card){
var id=card.dataset.id,cb=card.querySelector('.posted-cb');if(!cb)return;
if(p[id]){cb.checked=true;card.classList.add('done')}
cb.addEventListener('change',function(){var p=load();
if(cb.checked){p[id]=1;card.classList.add('done')}else{delete p[id];card.classList.remove('done')}
save(p);count()})});count()})})();
"""

SECTIONS = {
    "summary": r"##\s*📝[^\n]*\n(.*?)(?=\n##\s|\Z)",
    "fb": r"##\s*📘[^\n]*\n(.*?)(?=\n##\s|\Z)",
    "ig": r"##\s*📸[^\n]*\n(.*?)(?=\n##\s|\Z)",
    "hooks": r"##\s*🪝[^\n]*\n(.*?)(?=\n##\s|\Z)",
}


def parse_post(md: str) -> dict:
    out = {}
    for key, pat in SECTIONS.items():
        m = re.search(pat, md, re.S)
        out[key] = m.group(1).strip() if m else ""
    return out


def page_id(ep: dict, idx: int) -> str:
    m = re.search(r"episodes/([a-f0-9]+)", ep.get("page", "") or ep.get("guid", ""))
    return m.group(1) if m else f"ep{idx:02d}"


def html_page(title: str, body: str, root: str, footer: str) -> str:
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><header><div class="wrap"><a href="{root}index.html">← 一覧</a>
<h1>{html.escape(title)}</h1></div></header>
<div class="wrap">{body}</div>
<footer>{html.escape(footer)} — 社内用。<br>generated by stand-fm-scrape</footer>
<script>{COPY_JS}</script></body></html>"""


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the GitHub Pages site")
    ap.add_argument("-o", "--out", default="docs", type=Path)
    ap.add_argument("-t", "--transcripts", default="transcripts", type=Path)
    ap.add_argument("-p", "--posts", default="posts", type=Path)
    ap.add_argument("-s", "--summaries", default="summaries", type=Path)
    ap.add_argument("-m", "--manifest", default="manifest.json", type=Path)
    ap.add_argument("--with-transcripts", action="store_true", default=True,
                    help="embed full transcripts (default on)")
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    channel = manifest.get("channel", "channel")
    episodes = manifest["episodes"]

    # FS-level lookups, NFC-normalized to dodge filename normalization mismatches
    txts = {nfc(p.stem): p for p in args.transcripts.glob("*.txt")}
    posts = {nfc(p.stem): p for p in args.posts.glob("*.md") if not p.name.startswith("EXAMPLE_")}
    summaries = {nfc(p.stem): p for p in args.summaries.glob("*.md")}

    (args.out / "ep").mkdir(parents=True, exist_ok=True)

    cards = []
    built = 0
    transcribed = 0
    for idx, ep in enumerate(sorted(episodes, key=lambda e: e["date"], reverse=True)):
        stem = nfc(Path(ep["filename"]).stem)
        pid = page_id(ep, idx)
        title = ep["title"]
        listen = ep.get("page") or ep.get("guid") or ""
        has_post = stem in posts
        has_summary = stem in summaries
        has_txt = stem in txts
        if has_txt:
            transcribed += 1

        # ---- per-episode page ----
        body = [f'<p class="muted">{html.escape(ep["date"])}　'
                f'<a href="{html.escape(listen)}" target="_blank" rel="noopener">▶ stand.fmで聴く</a></p>']
        if has_post:
            P = parse_post(posts[stem].read_text(encoding="utf-8"))
            if P["summary"]:
                body.append(f'<div class="card"><h2>📝 概略（社内メモ）</h2>'
                            f'<p>{html.escape(P["summary"])}</p></div>')
            if P["fb"]:
                body.append(copybox("📘 Facebook（コピペ用）", P["fb"], f"fb{idx}"))
            if P["ig"]:
                body.append(copybox("📸 Instagram（コピペ用）", P["ig"], f"ig{idx}"))
            if P["hooks"]:
                body.append(f'<div class="card"><h2>🪝 フック候補</h2>'
                            f'<div style="white-space:pre-wrap">{html.escape(P["hooks"])}</div></div>')
            built += 1
        if has_summary:
            s = html.escape(summaries[stem].read_text(encoding="utf-8"))
            body.append(f'<div class="card"><h2>📋 エピソード要約</h2>'
                        f'<div style="white-space:pre-wrap">{s}</div></div>')
            if not has_post:
                built += 1
        if not has_post and not has_summary:
            body.append('<div class="card"><p class="pending">下書き・要約は未生成です'
                        '（文字起こし完了後に generate_posts.py / summarize_episodes.py で生成）。</p></div>')
        if args.with_transcripts and has_txt:
            t = html.escape(txts[stem].read_text(encoding="utf-8"))
            body.append(f'<details><summary>全文文字起こしを表示</summary>'
                        f'<div class="transcript">{t}</div></details>')

        (args.out / "ep" / f"{pid}.html").write_text(
            html_page(title, "\n".join(body), "../", channel), encoding="utf-8")

        # ---- index card ----
        status = ("✅ 下書きあり" if has_post else
                  ("📋 要約あり" if has_summary else
                   ("📝 文字起こし済" if has_txt else "⏳ 処理待ち")))
        cards.append(
            f'<div class="card" data-id="{pid}">'
            f'<label class="posted"><input type="checkbox" class="posted-cb">投稿済み</label>'
            f'<div class="ep-main"><span class="badge">{html.escape(ep["date"])}</span>'
            f'<span class="badge">{status}</span><br>'
            f'<a class="title" href="ep/{pid}.html">{html.escape(title)}</a></div></div>')

    total = len(episodes)
    pct = round(built / total * 100) if total else 0
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    progress = (
        '<div class="card">'
        f'<h2>進捗：下書き・要約完成 {built} / {total}本（{pct}%）</h2>'
        f'<div class="bar"><div class="bar-fill" style="width:{pct}%"></div></div>'
        f'<p class="muted">✅ 下書きあり {built}　／　📝 文字起こし済 {transcribed}　／　'
        f'⏳ 処理待ち {total - transcribed}</p>'
        f'<p class="muted">📮 投稿済み <b id="posted-count">0</b> / {total}本'
        '（チェックはこの端末に保存されます）'
        f'<br>最終更新: {updated}</p>'
        '</div>')
    posted_script = f'<script>{POSTED_JS % json.dumps("posted:" + channel, ensure_ascii=False)}</script>'
    index_body = (progress +
                  '<p class="muted">クリックでコピペ用ページへ。左の「投稿済み」に'
                  'チェックを付けると投稿済みの回を区別できます。</p>'
                  f'<div class="ep-list">{"".join(cards)}</div>'
                  + posted_script)
    (args.out / "index.html").write_text(
        html_page(f"{channel} — SNS下書き", index_body, "", channel), encoding="utf-8")
    # Pages: don't run Jekyll
    (args.out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built site → {args.out}/  ({len(episodes)} episodes, {built} with drafts)")


def copybox(label: str, text: str, eid: str) -> str:
    esc = html.escape(text)
    return (f'<div class="card"><h2>{label}</h2><div class="copybox">'
            f'<button class="copybtn" onclick="copyEl(\'{eid}\',this)">コピー</button>'
            f'<textarea id="{eid}" readonly>{esc}</textarea></div></div>')


if __name__ == "__main__":
    main()
