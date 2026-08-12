# Errors

Command failures and integration errors.

---

## [ERR-20260727-001] Xueqiu user_timeline API rate limit

**Time**: 2026-07-27T07:00-07:30 GMT+8
**Command**: python3 hunt_v3.py, hunt_v5.py (multiple)
**Error**: HTTP 400 on all user_timeline requests after ~10 rapid API calls
**Root Cause**: No delay between API requests; triggered WAF/rate limit
**Fix Applied**: Added 5-second sleep between calls, ran again after 5-min cooldown
**File**: /tmp/xueqiu_hunter/hunt_v5.py

## [ERR-20260727-002] Playwright WAF block on discussion pages

**Time**: 2026-07-27T06:45 GMT+8
**Command**: python3 scrape_discussions.py
**Error**: Aliyun WAF challenge page returned — 0 user IDs extracted from any stock discussion page
**Root Cause**: xueqiu.com/S/XXXXX is protected by Aliyun WAF; browser automation cannot bypass
**Fix Applied**: Abandoned discussion page scraping; focused on user_timeline API only
**File**: /tmp/xueqiu_hunter/scrape_discussions.py

## [ERR-20260727-003] Wrong regex for stock code extraction

**Time**: 2026-07-27T06:00 GMT+8
**Command**: Multiple early script versions
**Error**: `re.findall(r"HK(\d{5})", text)` found 0 matches in xueqiu posts
**Root Cause**: Posts use `$腾讯(00700)$` format, not `HK00700` embedded in text
**Fix Applied**: Changed to `re.findall(r"\((\d{5})\)", text)`
**File**: All hunt_*.py scripts


## [ERR-20260727-004] Playwright browser timeout

**Logged**: 2026-07-27T11:12:04.000Z
**Priority**: high
**Status**: active
**Area**: browser_automation

### Summary
Browser request timed out after 20006ms → Gateway timeout after 20000ms

### Details
- Tool: openclaw browser (Playwright)
- Timeout: 20006ms for browser request
- Same issue repeated at 11:31 (20001ms timeout)
- Root cause: Aliyun WAF challenge causes Playwright to hang/timeout

### Suggested Action
Discussion page scraping blocked by WAF. Only user_timeline API is reliable.

### Metadata
- Source: hook_auto
- Tags: browser, timeout, waf, xueqiu

---

## [ERR-20260727-005] Gateway restart fails with port busy

**Logged**: 2026-07-27T15:52:49.000Z
**Priority**: medium
**Status**: active
**Area**: infra

### Summary
openclaw gateway restart fails because port 18789 stays bound after kill signal

### Details
```
Gateway restart failed: Error: gateway port 18789 is still busy before LaunchAgent restart
- pid 11835 keeps holding port even after SIGTERM
```

### Suggested Action
Use `launchctl bootout gui/$(id -u)/ai.openclaw.gateway` instead of `openclaw gateway restart`

### Metadata
- Source: hook_auto
- Tags: gateway, restart, port, launchagent

---

## [ERR-20260727-006] Token mismatch on Control UI reconnect

**Logged**: 2026-07-27T16:06:33.000Z
**Priority**: low
**Status**: active
**Area**: infra

### Summary
Control UI token mismatch after gateway restart (code 1008)

### Suggested Action
Open fresh Control UI URL and re-authenticate after gateway restart

### Metadata
- Source: hook_auto
- Tags: auth, token, control-ui
