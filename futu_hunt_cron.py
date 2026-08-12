#!/usr/bin/env python3
"""Futu Discussion Hunter — Cron Script (no_agent mode)
Scrapes raw posts via OpenClaw Chrome CDP, outputs for semantic classification.
Delivery: local (to Hermes chat) — I classify and post to Discord.
"""
import json, subprocess, time, re, os, sys
from datetime import datetime
from pathlib import Path

TRACKED = {"00992", "00700", "09988", "09999", "03690", "01888", "09939", "06068"}
CDP_PORT = 18800
WS_BASE = "ws://127.0.0.1:" + str(CDP_PORT)
FUTU_HUNT = Path.home()/".openclaw/workspace/futu_hunt.js"
LIST_PAGES = Path.home()/".openclaw/workspace/list_pages.js"
OUT_DIR = Path.home()/"futu_hunter"
OUT_DIR.mkdir(exist_ok=True)

# ── CDP helpers ─────────────────────────────────────────────────────────────────

def cdp_pages():
    r = subprocess.run(["/opt/homebrew/bin/node", str(LIST_PAGES)],
        capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        sys.stderr.write("[cdp_pages] error: " + r.stderr.strip() + "\n")
        return []
    output = r.stdout.strip()
    if not output or output == "NONE":
        return []
    pages = []
    for line in output.split("\n"):
        if "|" in line:
            pid, url = line.split("|", 1)
            pages.append({"id": pid.strip(), "url": url.strip()})
    return pages

def find_community_page(pages):
    for p in pages:
        u = p.get("url","")
        if "community" in u and "futunn" in u.lower():
            return p["id"]
    return None

def ws_url(pid):
    return WS_BASE + "/devtools/page/" + pid

def cdp_nav(pid, url):
    r = subprocess.run(
        ["/opt/homebrew/bin/node", str(FUTU_HUNT), ws_url(pid), "nav", url],
        capture_output=True, text=True, timeout=30
    )
    return r.returncode == 0

def cdp_extract(pid):
    r = subprocess.run(
        ["/opt/homebrew/bin/node", str(FUTU_HUNT), ws_url(pid), "extract"],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode != 0:
        sys.stderr.write("[cdp_extract] error: " + r.stderr.strip() + "\n")
        return []
    try:
        return json.loads(r.stdout.strip())
    except Exception as e:
        sys.stderr.write("[cdp_extract] parse error: " + str(e) + "\n")
        return []

# ── Text cleaning ───────────────────────────────────────────────────────────────

_EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U00002600-\U000026FF\U00002700-\U000027BF]+",
    flags=re.UNICODE
)

def clean_text(text):
    """Strip reaction counts, emoji, and reply threads from raw post text."""
    # Remove ALL reaction count lines: \n1, \n2 etc. anywhere in text
    text = re.sub(r'\n\d+', '', text)
    # Remove emoji
    text = _EMOJI_PATTERN.sub('', text)
    # Remove stock title prefix: $NAME (CODE.HK)$
    text = re.sub(r"\$[^(]+\([^)]+\)\$", '', text)
    # Remove reply threads — stop at first "Name : reply" pattern
    lines = text.split('\n')
    clean_lines = []
    for l in lines:
        trimmed = l.strip()
        if not trimmed:
            continue
        if re.match(r'^[^,\n，]{1,30}\s+:', trimmed):
            break
        clean_lines.append(trimmed)
    return ' '.join(clean_lines).strip()[:200]

# ── AI post detection ───────────────────────────────────────────────────────────

def is_ai_post(text):
    """Reject obvious AI/boilerplate posts — keyword heuristics only."""
    if not text:
        return True
    score = 0
    for kw in ["作為AI","我是一個語言模型","我是AI","AI無法","ChatGPT",
               "LLM","大模型","我是基於","我的訓練數據"]:
        if kw in text:
            score += 5
    # Listicle structure: 首先/其次/再次/最後 x3+
    if len(re.findall(r"首先[，、]|其次[，、]|再次[，、]|最後[、]", text)) >= 3:
        score += 2
    return score >= 4

# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M HKT")
    sys.stdout.write(f"[Futu Hunt] Scan started {now}\n")
    sys.stdout.flush()

    pages = cdp_pages()
    page_id = find_community_page(pages)
    if not page_id:
        sys.stdout.write("[Futu Hunt] NO_SESSION\n")
        sys.stdout.flush()
        return

    sys.stdout.write(f"[Futu Hunt] Page: {page_id}\n")
    sys.stdout.flush()

    all_posts = []
    for stock in sorted(TRACKED):
        url = f"https://www.futunn.com/hk/stock/{stock}-HK/community"
        sys.stdout.write(f"[Futu Hunt] Scraping {stock}...")
        sys.stdout.flush()
        ok = cdp_nav(page_id, url)
        if not ok:
            sys.stdout.write(" NAV_FAIL\n")
            sys.stdout.flush()
            time.sleep(2)
            continue
        time.sleep(6)
        posts = cdp_extract(page_id)
        sys.stdout.write(f" {len(posts)} posts\n")
        sys.stdout.flush()
        for p in posts:
            p["stock_source"] = stock
        all_posts.extend(posts)
        time.sleep(2)

    # Deduplicate by fid
    seen, unique = set(), []
    for p in all_posts:
        fid = p.get("fid","")
        if fid and fid not in seen:
            seen.add(fid)
            unique.append(p)

    sys.stdout.write(f"[Futu Hunt] Deduped: {len(all_posts)} -> {len(unique)}\n")
    sys.stdout.flush()

    # Filter out obvious AI posts
    clean_posts = []
    for p in unique:
        raw = p.get("text","")
        ct = clean_text(raw)
        if is_ai_post(ct) or len(ct) < 10:
            continue
        uid = p.get("uid","")
        users = p.get("users", [])
        pu = next((u for u in users if u.get("id") == uid), None)
        nickname = pu["name"] if pu else (uid[:8] if uid else "?")
        clean_posts.append({
            "fid": p.get("fid",""),
            "uid": uid,
            "nickname": nickname,
            "stock": p.get("stock_source",""),
            "text": ct,
            "raw_text": raw,
            "time": p.get("time",""),
            "likes": p.get("like_count", 0),
            "replies": p.get("reply_count", 0),
        })

    sys.stdout.write(f"[Futu Hunt] After AI filter: {len(clean_posts)} posts\n\n")
    sys.stdout.flush()

    # Save raw posts to file
    out = {"scanned_at": now, "total": len(clean_posts), "posts": clean_posts}
    out_path = OUT_DIR / "raw_for_classification.json"
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # Format output for Hermes delivery
    sys.stdout.write("=" * 60 + "\n")
    sys.stdout.write(f"FUTU COMMUNITY SCAN — {now}\n")
    sys.stdout.write("=" * 60 + "\n\n")
    for i, p in enumerate(clean_posts, 1):
        likes = p.get("likes", 0) or 0
        replies = p.get("replies", 0) or 0
        sys.stdout.write(f"[{i:02d}] @{p['nickname']} ({p['stock']}) "
                         f"[{p['time']}] ★{likes} 💬{replies}\n")
        sys.stdout.write(f"    {p['text'][:150]}\n\n")
        sys.stdout.flush()

    sys.stdout.write("=" * 60 + "\n")
    sys.stdout.write(f"Total: {len(clean_posts)} posts for semantic classification\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
