---
name: xueqiu-discussion-hunter
description: Use when hunting predictive posts on xueqiu.com — fetches user timelines, verifies accuracy, ranks predictors, surfaces HK and US stock opportunities, and posts results to Discord.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [xueqiu, web-scraping, HK-stocks, US-stocks, social-sentiment, research, discord]
    related_skills: [arxiv, blogwatcher, grounded-citations, xurl]
---

# Xueqiu Discussion Hunter

Hunt predictive posts on xueqiu.com — fetch user timelines via API, verify accuracy against price moves, rank predictors, and surface HK stock opportunities.

> ⚠️ **Known limits (实测 2026-07-27):**
> - Discussion pages `/S/XXXXX` blocked by Aliyun WAF — Playwright cannot bypass
> - Search API `/v4/search/` returns 403
> - **Only reliable entry: `api.xueqiu.com/v4/statuses/user_timeline.json`**
> - Rate limit: **≥5 seconds between requests**, or HTTP 400 locks you out for 5 min

---

## AI-Generated Post Filter

Filter AI-generated posts at every stage:

```python
import re

def is_ai_post(text: str) -> tuple[bool, str, int]:
    if not text or len(text.strip()) < 10:
        return False, "", 0
    score = 0
    reasons = []

    # 1. Explicit self-reference to AI
    ai_self_ref = ["作为AI", "我是一个语言模型", "我是AI", "AI无法", "ChatGPT",
                   "LLM", "大模型", "我是基于", "我的训练数据"]
    for kw in ai_self_ref:
        if kw in text:
            score += 5; reasons.append(f"AI自述: {kw}")

    # 2. Over-structured enumeration
    structure_patterns = [r"首先[，、]", r"其次[，、]", r"再次[，、]", r"最后[、]",
                         r"第一[、。]", r"第二[、。]", r"第三[、。]"]
    for p in structure_patterns:
        if len(re.findall(p, text)) >= 3:
            score += 2; reasons.append("过度结构化枚举"); break

    # 3. No personal elements
    personal = ["我", "我的", "觉得", "感觉", "亏", "赚", "买", "卖", "持仓", "建仓", "被套", "割肉"]
    if sum(1 for w in personal if w in text) == 0:
        score += 2; reasons.append("无personal元素")

    # 4. Uniform paragraphs (too regular)
    paragraphs = [p.strip() for p in text.split('\n') if len(p.strip()) > 50]
    if len(paragraphs) >= 4:
        lens = [len(p) for p in paragraphs]
        if max(lens) - min(lens) < 50:
            score += 2; reasons.append("段落均匀得像AI")

    return score >= 4, "; ".join(reasons), score
```

- **score ≥ 4** → AI, exclude
- **score 2–3** → suspicious, retain but deprioritize
- **score 0–1** → genuine user, credible

---

## Workflow: Start from Stock Discussion Page

The workflow starts at `https://xueqiu.com/S/00700` → **讨论 tab**, scrapes posts, finds predictive users, then follows them to their profile pages.

### Step 1 — Navigate to stock page + 讨论 tab

```
browser_navigate("https://xueqiu.com/S/00700")
# Click 讨论 tab (ref=e19 in the page snapshot)
browser_click("e19")
```

### Step 2 — Scrape posts via CDP

Use `browser_console` to extract all posts from the current page:

```javascript
(function() {
  function getPosts() {
    var posts = [];
    document.querySelectorAll('article').forEach(function(a) {
      var uls = a.querySelectorAll('a[href*="/n/"]');
      var txt = (a.innerText || '').replace(/\n/g,' ').substring(0,400);
      var sc = [];
      a.querySelectorAll('a[href*="/S/"]').forEach(function(s) {
        var m = s.href.match(/\/S\/(\d{5})/); if(m) sc.push(m[1]);
      });
      if(uls.length > 0) {
        posts.push({
          user: uls[0].innerText.trim().replace('@',''),
          href: uls[0].href,  // https://xueqiu.com/n/{username}
          stocks: sc,
          text: txt.substring(0,200)
        });
      }
    });
    return posts;
  }
  return JSON.stringify(getPosts());
})();
```

### Step 3 — Pagination

Xueqiu is an SPA — `?page=N` does NOT update the article container.
Must click page links via CDP, then wait ~800ms for re-render:

```javascript
// Click page 2, wait, extract
function clickPage(n) {
  var links = document.querySelectorAll('a');
  for (var i=0;i<links.length;i++){
    if (links[i].innerText.trim() === String(n)){ links[i].click(); return true; }
  }
  return false;
}
clickPage(2);
// Wait 800ms for SPA to re-render
var t=Date.now(); while(Date.now()-t < 800){}
getPosts();  // now returns page-2 content
```

### Step 4 — Resolve user ID from profile URL

Profile URLs from posts are `/n/{username}` (not `/u/{uid}`).
**Important:** numeric `uid` is NOT derivable from the username path.
You need to visit the profile page to get the uid, or use the API with known uid list.

```
browser_navigate("https://xueqiu.com/n/{username}")
# Extract from page title: "用户名 - 雪球"
# Or use the user_timeline API with known uid from prior research
```

### Step 5 — Fetch all HK stock predictions from profile

Use the user timeline API — it returns `created_at` as Unix **milliseconds** (int):

```python
import time, requests, re
from datetime import datetime

url = f"https://api.xueqiu.com/v4/statuses/user_timeline.json?user_id={uid}&page=1&count=20&_={int(time.time())}"
r = requests.get(url, headers=headers, timeout=10)
statuses = r.json().get("statuses", [])
for s in statuses:
    # created_at is Unix milliseconds (int), NOT ISO string
    dt = datetime.fromtimestamp(s["created_at"] / 1000)
    raw_text = s.get("text", "")
    # Extract HK stock codes from $名称(代码)$ format
    codes = re.findall(r"\$[^$]*?\((\d{5})\)\$", raw_text)
```

---

## API WAF Bypass

Xueqiu uses Aliyun WAF — stock/user pages trigger sliding challenges.
**Solution: use `api.xueqiu.com` endpoints directly.**

```
✅ https://api.xueqiu.com/v4/statuses/user_timeline.json?user_id={id}&page=1&count=20
✅ https://xueqiu.com/u/{uid}   (profile page — works for uid lookup)
✅ https://xueqiu.com/n/{username}  (profile page by username)
❌ https://xueqiu.com/v4/search/users.json         → 403
❌ https://stock.xueqiu.com/v5/stock/quote.json     → HK quotes return null
❌ https://xueqiu.com/S/00700 (discussion tab via web_extract) → SPA, no content
❌ https://xueqiu.com/v4/search/status.json         → 403
```

**Get cookies:**
```bash
openclaw browser cookies > /tmp/xueqiu_cookies.json
```

---

## Direction Detection

```python
def detect_direction(text: str) -> str:
    t = re.sub(r"<[^>]+>", "", text)  # strip HTML tags
    bull_kw = ["上涨","大涨","看好","买入","加仓","做多","反弹","突破","抄底","低估",
               "持有","满仓","建仓","买","会涨","上行","上升","拉升","牛","多","继续持有",
               "强劲","强势","增长","业绩","增持","终点","绝对不是","绝不是","10万亿",
               "20万亿","30万亿","天花板","值得","分红","回购","利润","目标价","中概之光",
               "国货之光","发布会前","长期目标","低估值"]
    bear_kw = ["下跌","大跌","看跌","做空","止损","割肉","跌","跌破","弱势","清仓","减持",
               "不看好","避开","空仓","崩","不值","还会跌","减仓","跑","不建议","看空","高估"]

    bull_count = sum(1 for w in bull_kw if w in t)
    bear_count = sum(1 for w in bear_kw if w in t)

    # Context boosts
    if "强" in t and len(t) < 200: bull_count += 2
    if "终点" in t or "天花板" in t: bull_count += 3
    if "绝对不是" in t or "绝不是" in t: bull_count += 3
    if "值得" in t and len(t) < 150: bull_count += 2
    if "低估值" in t or "低估" in t: bull_count += 4

    if bull_count > bear_count + 1: return "bullish"
    if bear_count > bull_count + 1: return "bearish"
    return "neutral"
```

---

## Stock Code Extraction

Xueqiu posts use `$名称(代码)$` format — extract correctly:

```python
import re

def extract_stocks(text: str) -> list[str]:
    """Extract HK stock 5-digit codes from $名称(代码)$ format."""
    return re.findall(r"\((\d{5})\)", text)

# Example
extract_stocks("$小米集团-W(01810)$ $腾讯(00700)$")  # → ['01810', '00700']

# ❌ WRONG: only matches URLs, not post content
# re.findall(r"HK(\d{5})", text)
```

---

## Rate-Limit-Safe API Calls

```python
import time, requests

def mk_headers(cookies: list[dict]) -> dict:
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies if c.get('value'))
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": cookie_str,
        "Referer": "https://xueqiu.com",
    }

def get_timeline(uid: int, headers: dict) -> list[dict]:
    time.sleep(5)  # MUST wait ≥5s or HTTP 400
    url = f"https://api.xueqiu.com/v4/statuses/user_timeline.json?user_id={uid}&page=1&count=20"
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        return r.json().get("statuses", [])
    return []
```

**实测:**
- 10+ rapid requests → HTTP 400, 5-min lockout
- 5s gap between requests → zero failures

---

## Leaderboard: Top-20 Predictor Tracker

Maintains a **ranked top-20 leaderboard** of the most accurate HK-stock predictors.
Persisted to `~/xueqiu_hunter/leaderboard.json`.

### Core Class

```python
import json, os
from datetime import datetime
from pathlib import Path

LEADERBOARD_PATH = Path.home() / "xueqiu_hunter" / "leaderboard.json"

class LeaderboardTracker:
    """Track top-20 HK-stock predictors ranked by prediction accuracy."""

    def __init__(self, path: str = str(LEADERBOARD_PATH)):
        self.path = Path(path)
        self.data = self._load()

    # ── Persistence ──────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {"predictions": [], "ranked": []}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    # ── Scoring ─────────────────────────────────────────────────────────────────

    @staticmethod
    def score_prediction(prediction: dict, price_data: dict) -> float | None:
        """
        Compare a user's stock+direction prediction against actual price movement.

        price_data keys: {entry_price, exit_price, direction}
        direction: 'bullish' → actual price should go UP
                    'bearish' → actual price should go DOWN

        Returns accuracy score:
          1.0  = correct direction + magnitude
          0.7  = correct direction
          0.3  = wrong direction
          0.0  = no price data available (pending verification)
          None = skip (e.g. neutral direction)
        """
        if prediction.get("direction") == "neutral":
            return None

        stock  = prediction["stock"]
        pred_dir = prediction["direction"]
        if stock not in price_data:
            return None

        pd = price_data[stock]
        entry = pd["entry_price"]
        actual = pd["exit_price"]
        pct_chg = (actual - entry) / entry  # fraction

        # Correct direction
        if pred_dir == "bullish" and pct_chg > 0.005:   # >0.5% up
            return 1.0
        if pred_dir == "bearish" and pct_chg < -0.005:   # >0.5% down
            return 1.0
        # Correct direction, small move
        if pred_dir == "bullish" and pct_chg > 0:
            return 0.7
        if pred_dir == "bearish" and pct_chg < 0:
            return 0.7
        # Wrong direction
        return 0.3

    # ── Leaderboard Management ──────────────────────────────────────────────────

    def add_prediction(self, uid: int, user: str, stock: str,
                      direction: str, text_preview: str,
                      confidence: float = 0.5) -> None:
        """
        Record a new prediction and re-rank the top-20.

        confidence: 0.0–1.0 manual override (default 0.5)
        """
        pred_id = f"{uid}_{stock}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Check for duplicate (same user+stock+today) — skip if exists
        today = datetime.now().strftime("%Y-%m-%d")
        for p in self.data["predictions"]:
            if (p["uid"] == uid and p["stock"] == stock
                    and p["created"][:10] == today):
                return  # already recorded today

        prediction = {
            "id": pred_id,
            "uid": uid,
            "user": user,
            "stock": stock,
            "direction": direction,
            "text": text_preview[:120],
            "confidence": confidence,
            "created": datetime.now().isoformat(),
            "accuracy": None,   # filled by verify_and_update()
            "verified": False,
        }
        self.data["predictions"].append(prediction)
        self._re_rank()

    def verify_and_update(self, uid: int, stock: str,
                          entry_price: float, exit_price: float) -> float | None:
        """
        Verify all unverified predictions for uid+stock pair.
        Fills `accuracy` field, returns the accuracy score.
        """
        score = None
        for p in self.data["predictions"]:
            if p["uid"] == uid and p["stock"] == stock and not p["verified"]:
                pct = (exit_price - entry_price) / entry_price
                if p["direction"] == "bullish":
                    s = 1.0 if pct > 0.005 else (0.7 if pct > 0 else 0.3)
                elif p["direction"] == "bearish":
                    s = 1.0 if pct < -0.005 else (0.7 if pct < 0 else 0.3)
                else:
                    s = None
                p["accuracy"] = s
                p["verified"] = True
                p["exit_price"] = exit_price
                score = s
        if score is not None:
            self._re_rank()
            self.save()
        return score

    def _re_rank(self):
        """
        Re-rank all users by average accuracy across their verified predictions.
        Keeps top 20; drops the lowest-accuracy user when a new one qualifies.
        """
        from collections import defaultdict

        # Aggregate by user
        user_scores: dict = defaultdict(list)
        for p in self.data["predictions"]:
            if p["accuracy"] is not None:
                user_scores[(p["uid"], p["user"])].append(p["accuracy"])

        # Compute average
        ranked = []
        for (uid, user), scores in user_scores.items():
            avg = sum(scores) / len(scores)
            ranked.append({
                "uid": uid,
                "user": user,
                "avg_accuracy": round(avg, 3),
                "n_predictions": len(scores),
                "recent_stocks": self._recent_stocks(uid),
            })

        ranked.sort(key=lambda x: x["avg_accuracy"], reverse=True)
        self.data["ranked"] = ranked[:20]   # top 20 only

    def _recent_stocks(self, uid: int, n: int = 3) -> list[str]:
        recent = [p["stock"] for p in self.data["predictions"]
                  if p["uid"] == uid]
        seen, out = [], []
        for s in reversed(recent):
            if s not in seen: seen.append(s); out.insert(0, s)
            if len(out) >= n: break
        return out

    def get_top20(self) -> list[dict]:
        return self.data["ranked"]

    def add_new_user(self, uid: int, user: str) -> str:
        """
        Bootstrap a brand-new user (no history) onto the leaderboard
        with 0 predictions so far. Returns 'added' or 'already_present'.
        """
        existing = [r for r in self.data["ranked"] if r["uid"] == uid]
        if existing:
            return "already_present"
        # Seed with 0 avg so they appear at the bottom until verified
        new_entry = {
            "uid": uid, "user": user,
            "avg_accuracy": 0.0, "n_predictions": 0,
            "recent_stocks": [],
        }
        self.data["ranked"].append(new_entry)
        self.data["ranked"].sort(key=lambda x: x["avg_accuracy"], reverse=True)
        self.data["ranked"] = self.data["ranked"][:20]
        self.save()
        return "added"

    def get_user_rank(self, uid: int) -> int | None:
        ranked = self.data["ranked"]
        for i, r in enumerate(ranked):
            if r["uid"] == uid:
                return i + 1   # 1-indexed
        return None

    # ── Human-readable dump ──────────────────────────────────────────────────────

    def print_leaderboard(self):
        print(f"\n{'#':<3} {'User':<20} {'Acc':>5} {'N':>3}  {'Recent stocks'}")
        print("-" * 60)
        for i, r in enumerate(self.data["ranked"], 1):
            print(f"{i:<3} {r['user']:<20} {r['avg_accuracy']:>5.3f} "
                  f"{r['n_predictions']:>3}  {r['recent_stocks']}")
```

### Leaderboard Data File

`~/xueqiu_hunter/leaderboard.json` — persisted leaderboard:

```json
{
  "predictions": [
    {
      "id": "1487331530_03690_20260804111800",
      "uid": 1487331530,
      "user": "4点起床读财报",
      "stock": "03690",
      "direction": "bullish",
      "text": "抖音竟然只有一线城市没突破了，不说别的...",
      "confidence": 0.5,
      "created": "2026-08-04T11:18:00",
      "accuracy": null,
      "verified": false
    }
  ],
  "ranked": [
    {
      "uid": 1487331530,
      "user": "4点起床读财报",
      "avg_accuracy": 0.875,
      "n_predictions": 8,
      "recent_stocks": ["03690", "00700", "01810"]
    }
  ]
}
```

### Integration: Hunt → Leaderboard Pipeline

```python
def run_hunt_with_leaderboard(cookies: list[dict]) -> LeaderboardTracker:
    tracker = LeaderboardTracker()
    headers = mk_headers(cookies)

    # Discover new users from stock discussion pages (CDP approach)
    # Then for each known predictor:
    for uid, name in USERS:
        statuses = get_timeline(uid, headers)
        for s in statuses:
            text = s.get("text", "")
            if is_ai_post(text)[0]:
                continue
            direction = detect_direction(text)
            stocks = extract_stocks(text)
            for stock in stocks:
                tracker.add_prediction(
                    uid=uid, user=name,
                    stock=stock, direction=direction,
                    text_preview=text[:120]
                )
        time.sleep(5)

    tracker.save()
    tracker.print_leaderboard()
    return tracker
```

---

## Known Top Predictors (ranked by accuracy)

Updated dynamically by `LeaderboardTracker`. Seed data:

| Rank | User | UID | Specialty | Key Calls |
|------|------|-----|-----------|-----------|
| 1 | 4点起床读财报 | 1487331530 | Xiaomi launch + Meituan | 03690✅ 01810✅ |
| 2 | 乌云蔽日 | 9233071504 | Meituan momentum | 03690✅ (突破年线→120) |
| 3 | 修长城的人 | 9739866425 | Xiaomi long-term targets | 01810✅ |
| 4 | 我是舵手007 | 5543581502 | Xiaomi (01810) | 01810🟡 (加仓机会) |
| 5 | 静水流深2020 | 3381323899 | HK tech | 00981🟡 (缩量信号) |
| 6 | Shark2024 | 5821540389 | Tencent (00700) | 00700⚠️ (bearish miss) |
| 7 | 金融Ai拖拉机001 | 8785218821 | HK biotech | 02410 02228 |
| 8 | 量化投资小20 | 5038411894 | HK quant | — |

---

## Quick Run

```python
import json, time, requests, re
from datetime import datetime, date

USERS = [
    (9233071504, "乌云蔽日"),
    (5821540389, "Shark2024"),
    (9739866425, "修长城的人"),
    (1487331530, "4点起床读财报"),
    (5543581502, "我是舵手007"),
    (3381323899, "华仁_W"),
    (1054707264, "饕餮和汉堡"),
    (8920332382, "大盘基爱好者"),
]

def run_hunt(cookies: list[dict]) -> list[dict]:
    headers = mk_headers(cookies)
    today_str = date.today().isoformat()
    results = []

    for uid, name in USERS:
        statuses = get_timeline(uid, headers)
        for s in statuses:
            created = s.get("created_at", "")
            if today_str not in created:
                continue
            text = s.get("text", "")
            if is_ai_post(text)[0]:
                continue
            stocks = extract_stocks(text)
            direction = detect_direction(text)
            if direction != "neutral" and stocks:
                results.append({
                    "user_id": uid, "user": name,
                    "direction": direction,
                    "stocks": stocks,
                    "text": text[:200],
                    "created_at": created,
                })
        time.sleep(5)  # respect rate limit

    # ── Post to Discord ─────────────────────────────────────────────────────────
    tracker = LeaderboardTracker()
    top5 = tracker.get_top20()[:5]
    post_to_discord(results, market="HK", leaderboard_top5=top5)
    # ───────────────────────────────────────────────────────────────────────────

    return results
```

---

## Discord Webhook

**Always post results to Discord after every hunt run.**

```python
import requests
from datetime import datetime

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1531888048797782026/JEmDHBY2PkJjDqoQQFVyJBnXX2hK-lrYbjDPYlMGJls0p6J26oRVMhBCjdU4bafguHtj"

def post_to_discord(results: list[dict], market: str = "HK",
                     leaderboard_top5: list[dict] = None) -> None:
    """
    Post hunt results + leaderboard snapshot to Discord.
    market: 'HK' or 'US'
    """
    today = datetime.now().strftime("%Y-%m-%d")
    emoji_map = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}
    color_map = {"HK": 16711680, "US": 3447003}   # red for HK, blue for US

    # Group by direction
    bullish = [r for r in results if r.get("direction") == "bullish"]
    bearish = [r for r in results if r.get("direction") == "bearish"]

    fields = []

    # HK stock calls
    if market == "HK":
        stock_label = "🇭🇰 HK Stock Calls"
    else:
        stock_label = "🇺🇸 US Stock Calls"

    for r in results[:8]:
        emoji = emoji_map.get(r.get("direction"), "⚪")
        stock_list = ", ".join(r.get("stocks", []))
        user = r.get("user", "unknown")
        text = r.get("text", "")[:80].replace("\n", " ")
        fields.append({
            "name": f"{emoji} {stock_list}",
            "value": f"**{user}**: {text}...",
            "inline": False
        })

    if not results:
        fields.append({
            "name": "❌ No directional calls today",
            "value": "No tracked users posted actionable predictions today.",
            "inline": False
        })

    # Leaderboard top 5
    lb_fields = []
    if leaderboard_top5:
        for i, entry in enumerate(leaderboard_top5, 1):
            user = entry.get("user", "?")
            acc = entry.get("avg_accuracy", 0)
            n = entry.get("n_predictions", 0)
            recent = ", ".join(entry.get("recent_stocks", [])[:3])
            lb_fields.append({
                "name": f"#{i} {user}",
                "value": f"Acc: {acc:.3f} ({n} calls) | {recent}",
                "inline": False
            })

    # Build embed
    embed = {
        "title": f"{'🇭🇰' if market=='HK' else '🇺🇸'} xueqiu {market} Stock Calls — {today}",
        "color": color_map.get(market, 5817228),
        "footer": {"text": "Source: xueqiu.com | Bot: Hermes Agent"},
        "fields": fields
    }

    if lb_fields:
        embed2 = {
            "title": "🏆 Top 5 Leaderboard",
            "color": 16486904,
            "fields": lb_fields
        }
        payload = {
            "thread_name": f"xueqiu {market} Stock {today}",
            "content": f"{'🇭🇰' if market=='HK' else '🇺🇸'} **xueqiu {market} Stock Predictions — {today}**",
            "embeds": [embed, embed2]
        }
    else:
        payload = {
            "thread_name": f"xueqiu {market} Stock {today}",
            "content": f"{'🇭🇰' if market=='HK' else '🇺🇸'} **xueqiu {market} Stock Predictions — {today}**",
            "embeds": [embed]
        }

    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if r.status_code == 204:
        print("✅ Posted to Discord")
    else:
        print(f"⚠️ Discord POST failed: {r.status_code} {r.text[:100]}")

def post_us_results_to_discord(results: list[dict], today_str: str = None) -> None:
    """Specialized Discord formatter for US stock results."""
    today = today_str or datetime.now().strftime("%Y-%m-%d")
    emoji_map = {"bullish": "🟢", "bearish": "🔴"}

    fields = []
    for r in results[:10]:
        emoji = emoji_map.get(r.get("direction"), "⚪")
        stocks = ", ".join(r.get("stocks", []))
        user = r.get("user", "?")
        text = r.get("text", "")[:80].replace("\n", " ")
        fields.append({
            "name": f"{emoji} {stocks} ({r.get('direction', '')})",
            "value": f"**{user}**: {text}...",
            "inline": False
        })

    if not fields:
        fields = [{"name": "❌ No directional calls", "value": "No tracked xueqiu users posted today.", "inline": False}]

    embed = {
        "title": f"🇺🇸 US Stock Predictions — xueqiu | {today}",
        "color": 3447003,
        "fields": fields,
        "footer": {"text": "Source: xueqiu.com | Bot: Hermes Agent"}
    }

    payload = {
        "thread_name": f"xueqiu US Stock {today}",
        "content": f"🇺🇸 **xueqiu US Stock Predictions — {today}**",
        "embeds": [embed]
    }

    r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    print(f"Discord: {r.status_code}", "✅" if r.status_code == 204 else r.text[:100])
```

**Forum channel rule:** Discord webhooks to forum channels require `thread_name` in every payload — plain content/embed-only posts fail with `code 220001`.

---

## Output Files

| File | Description |
|------|-------------|
| `~/xueqiu_hunter/final_clean_YYYYMMDD.json` | Latest full analysis (HK + US) |
| `~/xueqiu_hunter/p1_timelines.json` | Phase 1 — user timelines |
| `~/xueqiu_hunter/p2_verified.json` | Phase 2 — accuracy-ranked |
| `~/xueqiu_hunter/p3_opportunities.json` | Phase 3 — today's opportunities |
| `~/xueqiu_hunter/us_results_YYYYMMDD.json` | US stock hunt results |
| `~/xueqiu_hunter/leaderboard.json` | Top-20 predictor leaderboard |

---

## Cookie Refresh

**Check before every run:**

```python
import subprocess, json

result = subprocess.run(
    ["openclaw", "browser", "cookies"],
    capture_output=True, text=True, timeout=15
)
cookies = json.loads(result.stdout)
xq = [c for c in cookies if "xueqiu" in c.get("domain", "") and c.get("value")]
xq_is_login = [c for c in xq if c["name"] == "xq_is_login"]
print(f"Xueqiu cookies: {len(xq)}, logged in: {len(xq_is_login)}")
if xq_is_login:
    print("✅ 登录状态有效")
else:
    print("⚠️ 未登录或 session 已过期，需要在浏览器登录雪球")
```

---

## Known Limits

| Issue | Status | Workaround |
|-------|--------|-----------|
| Discussion pages `/S/XXXXX` | ❌ WAF blocked | Use user_timeline API only |
| Search API `/v4/search/` | ❌ 403 | None |
| HK stock quotes API | ❌ Returns null | Use Futu or Yahoo Finance |
| Rate limit | ⚠️ 5s/request | Strict `time.sleep(5)` |
| Discovering new users | ⚠️ Manual | Follow top predictors' follows |

---

## Verification Checklist

- [ ] `is_ai_post` correctly excludes AI-generated content (score ≥ 4)
- [ ] `extract_stocks` parses `$名称(代码)$` correctly (not URL format)
- [ ] `time.sleep(5)` present between every API call
- [ ] Cookies include `xq_is_login` — confirmed logged in before run
- [ ] Direction detection keywords are current (no stale HK stock terminology)
- [ ] Output JSON saved with today's date in filename
- [ ] All 8 known users have been checked for new direction posts
