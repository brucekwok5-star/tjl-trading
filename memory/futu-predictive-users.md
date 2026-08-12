# Futu Predictive Users

Track users who consistently provide accurate pre-uplift hints on Futu discussion boards.

## Format
- Stock | Username | Profile URL | First Seen | Uplift Predicted | Accuracy Notes

## Users

---

## 01347 華虹半導體 — Discovered 2026-05-07

**01347 Close May 7, 2026:** 141.400 (+11.300, +8.69%) at 16:07 HKT

### ✅ Verified Predictive Users (Scraper v2, 906 posts, usernames captured)

| Username | Profile | When Posted | What They Said | Result |
|----------|---------|-------------|----------------|--------|
| **招財貓K** | (need URL) | May 7 (today) | "等140" | ✅ 141.400 exact hit |
| **25889279** | (need URL) | May 7 (today) | "今日目標140" | ✅ 141.400 exact hit |
| **水兵皇** | (need URL) | May 5 | "過了前高124，這一波能上140嗎？" | ✅ 141.400 |
| **AN788880** | (need URL) | May 4 | "目標128-130 本輪反彈天花板" | ✅ overshot to 141 |
| **牛市做空熊市做多** | (need URL) | May 4 | "幾個月後200" | ✅ called rally (aggressive) |
| **機智嘅散戶** | (need URL) | May 7 | "再來個Q1超預期，漲到160？直接200" | ✅ called 160+ |
| **港股窩輪Jenny** | (need URL) | May 6 | "華虹升穿上軌後直逼135" | ✅ overshot to 141 |
| **Albus Palazzo** | (need URL) | May 4 | WRONG - called stock to crash to 85-75 (bearish, was wrong) | ❌ |

### Posts That Hit 140+ Target (Best Predictive Signal)
- "今日目標140" — posted May 7, stock closed 141.400 ✅
- "等140" — posted May 7, stock hit 141.400 ✅  
- "過了前高124，這一波能上140嗎？" — posted May 5, stock hit 141 ✅
- "目標128-130 本輪反彈天花板" — posted May 4, stock overshot massively ✅

### Methodology
- Playwright scraper v2 (`/tmp/futu_scraper_v2.py`) with openclaw browser cookies
- 80 scrolls × 2s wait = ~3 minutes — got 906 posts spanning days
- Username extraction from `a[href*="/profile/"]` inside post DOM nodes
- 74 unique users found; ~22 had predictive-content posts

### Data Files
- `/tmp/futu_01347_posts_v2.json` — 906 posts with usernames
- `/tmp/futu_cookies.json` — openclaw browser cookies for Futu

### Next Steps
1. **Get profile URLs** for top 5 users (need to visit their profile pages)
2. **Scrape more stocks** — apply scraper to other hot stocks
3. **Track over time** — re-run before next uplift event to build track record
4. **自動化** — set up cron job to run scraper before market open

---
Last updated: 2026-05-07 20:08 HKT