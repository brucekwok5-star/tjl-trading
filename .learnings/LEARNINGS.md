# Learnings

Corrections, insights, and knowledge gaps captured during development.

**Categories**: correction | insight | knowledge_gap | best_practice

---

## [LRN-20250606-001] best_practice

**Logged**: 2026-06-06T06:20:00Z
**Priority**: medium
**Status**: promoted
**Area**: infra

### Summary
Use `openclaw hooks enable` instead of manually editing hook config files

### Details
When enabling a hook, directly running `cp` then `openclaw hooks enable` fails if the destination dir doesn't exist. Must `mkdir -p ~/.openclaw/hooks` first, THEN copy the hook dir, THEN run the enable command. The enable command itself doesn't create the parent directory.

### Suggested Action
Document this in TOOLS.md: always `mkdir -p ~/.openclaw/hooks` before copying hook directories.

### Metadata
- Source: error
- Related Files: ~/.openclaw/hooks/
- Tags: openclaw, hooks, setup
- Pattern-Key: setup.hook-enable
- Recurrence-Count: 1
- First-Seen: 2026-06-06
- Last-Seen: 2026-06-06

---

## [LRN-20260727-001] insight

**Logged**: 2026-07-27T07:15:00Z
**Priority**: high
**Status**: active
**Area**: xueqiu-scraping

### Summary
Xueqiu stock posts use `$腾讯(00700)$` format — extract code with `\(\d{5}\)`, NOT `HK(\d{5})`

### Details
Xueqiu posts embed stock tickers as `$股票名称(代码)$` — e.g. `$美团-W(03690)$`. The HK prefix `HK` only appears in URLs (`/S/00700`), not in post content. My regex `HK(\d{5})` found zero matches. The correct extraction is `re.findall(r"\(\d{5}\)", text)`.

### Suggested Action
Always verify the actual HTML/text format before writing extractors. Test against real page content first.

### Metadata
- Source: error
- Related Files: /tmp/xueqiu_hunter/hunt_*.py
- Tags: xueqiu, regex, scraping, stock-extraction
- Pattern-Key: xueqiu.stock-code-format
- Recurrence-Count: 1
- First-Seen: 2026-07-27
- Last-Seen: 2026-07-27

---

## [LRN-20260727-002] error

**Logged**: 2026-07-27T07:15:00Z
**Priority**: high
**Status**: active
**Area**: xueqiu-scraping

### Summary
Xueqiu discussion pages blocked by Aliyun WAF — Playwright returns challenge page, not real content

### Details
Accessing `https://xueqiu.com/S/00700` via Playwright returns HTML with `<meta name="aliyun_waf_aa" content="...">` — an Aliyun WAF challenge page. Zero user links or post content extracted. This means `/S/XXXXX` discussion pages cannot be scraped via any browser automation method without solving captcha.

**Also confirmed:**
- `/v4/search/` API → 403 Forbidden
- Public timeline API `public_timeline_by_category` → returns empty items (null data)

**Working:**
- `/v4/statuses/user_timeline.json?user_id=XXXX` → ✅ 200 OK
- `/v4/users/show.json?user_id=XXXX` → ✅ 200 OK

### Suggested Action
Do NOT try to scrape discussion pages. Only use user_timeline API. Accept that expanding user pool beyond known predictor list requires manual discovery or other discovery methods.

### Metadata
- Source: error
- Related Files: /tmp/xueqiu_hunter/scrape_discussions.py
- Tags: xueqiu, WAF, scraping, blocked
- Pattern-Key: xueqiu.waf-blocked
- Recurrence-Count: 1
- First-Seen: 2026-07-27
- Last-Seen: 2026-07-27

---

## [LRN-20260727-003] best_practice

**Logged**: 2026-07-27T07:15:00Z
**Priority**: high
**Status**: active
**Area**: xueqiu-api

### Summary
Xueqiu user_timeline API rate-limits after ~10 rapid requests (400 errors) — need 5s delay between calls

### Details
Calling the timeline API for 15 users back-to-back triggered rate limiting (HTTP 400). After ~5 minutes cooldown it recovered. With 5-second delays between calls, all requests succeeded. Also: requests made in background `exec` sessions get `SIGTERM` before producing output — always use foreground exec for API calls that need to see response.

### Suggested Action
Always `time.sleep(5)` between timeline API calls. Cache results to file immediately. Use foreground exec (not background) for API testing.

### Metadata
- Source: error
- Related Files: /tmp/xueqiu_hunter/hunt_*.py
- Tags: xueqiu, rate-limit, API, best-practice
- Pattern-Key: xueqiu.rate-limit
- Recurrence-Count: 1
- First-Seen: 2026-07-27
- Last-Seen: 2026-07-27

---
