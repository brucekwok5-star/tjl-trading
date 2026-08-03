#!/usr/bin/env python3
"""
scrape_all.py — scrape JobsDB, eFinancialCareers, and Indeed.
Usage:
    python3 scrape_all.py [KEYWORDS] [DAYS]
"""

import sys
import json
import random
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

# Resolve config relative to this script's location
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import config


def human_delay():
    time.sleep(random.uniform(config.HUMAN_DELAY_MIN, config.HUMAN_DELAY_MAX))


def load_cookies(ctx, site_name: str):
    """Try to load cached cookies, filtering by site name."""
    if not config.COOKIE_FILE.exists():
        return
    try:
        raw = json.loads(config.COOKIE_FILE.read_text())
        for c in raw:
            domain = c.get("domain", "").lower()
            if site_name.lower() in domain or "jobsdb" in domain or "efinancial" in domain or "indeed" in domain:
                try:
                    ctx.add_cookies([c])
                except Exception:
                    pass
    except Exception as e:
        print(f"[WARN] Could not load cookies: {e}")


def detect_antiblock(page) -> bool:
    """Return True if page looks blocked."""
    text = page.inner_text("body").lower()
    blockers = [
        "access to this page has been denied",
        "access denied",
        "please verify you are a human",
        "captcha",
        "challenge",
        "blocked",
        "弥合",
        "人机验证",
    ]
    return any(b in text for b in blockers)


def scrape_site(name: str, cfg: dict, keywords: str, days: int) -> list[dict]:
    """Scrape one job site. Returns list of job dicts."""
    encoded_kw = urllib.parse.quote(keywords)
    url = cfg["url"].format(keywords=encoded_kw, days=days)
    print(f"\n=== Scraping {name} ===")
    print(f"URL: {url}")

    results = []
    attempts = 0

    while attempts < config.RETRY_COUNT:
        attempts += 1
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                ctx = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                ctx.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                })

                load_cookies(ctx, name)

                page = ctx.new_page()
                page.goto(url, timeout=60_000, wait_until="domcontentloaded")
                human_delay()

                if detect_antiblock(page):
                    print(f"[{name}] ⚠️  Anti-bot detected (attempt {attempts})")
                    browser.close()
                    if attempts < config.RETRY_COUNT:
                        print(f"[{name}] Waiting {config.RETRY_DELAY_SEC}s before retry...")
                        time.sleep(config.RETRY_DELAY_SEC)
                        continue
                    else:
                        print(f"[{name}] Giving up after {config.RETRY_COUNT} attempts.")
                        return results

                # Scroll to lazy-load more results
                for _ in range(config.SCROLL_ITERATIONS):
                    page.evaluate("window.scrollBy(0, 600)")
                    time.sleep(config.SCROLL_PAUSE_SEC)

                # Find job cards
                cards = []
                for sel in cfg["job_card_sel"]:
                    cards = page.query_selector_all(sel)
                    if cards:
                        print(f"[{name}] Found {len(cards)} cards with selector: {sel}")
                        break

                for card in cards:
                    try:
                        # Title
                        title = ""
                        for sel in cfg["title_sel"]:
                            el = card.query_selector(sel)
                            if el:
                                title = el.inner_text().strip()
                                if len(title) > 3:
                                    break

                        # Company
                        company = ""
                        for sel in cfg["company_sel"]:
                            el = card.query_selector(sel)
                            if el:
                                company = el.inner_text().strip()
                                break

                        # Location
                        location = ""
                        for sel in cfg["location_sel"]:
                            el = card.query_selector(sel)
                            if el:
                                location = el.inner_text().strip()
                                break

                        # Posted
                        posted = ""
                        for sel in cfg["posted_sel"]:
                            el = card.query_selector(sel)
                            if el:
                                posted = el.inner_text().strip()
                                break

                        # Salary
                        salary = ""
                        for sel in cfg["salary_sel"]:
                            el = card.query_selector(sel)
                            if el:
                                salary = el.inner_text().strip()
                                break

                        # Link
                        link = ""
                        link_el = card.query_selector(cfg["link_sel"])
                        if link_el:
                            raw_href = link_el.get_attribute("href") or ""
                            if raw_href.startswith("http"):
                                link = raw_href
                            elif raw_href.startswith("/"):
                                link = cfg["link_prefix"] + raw_href

                        if title:
                            results.append({
                                "title": title[:150],
                                "company": company[:80] if company else "N/A",
                                "location": location[:80] if location else "N/A",
                                "posted": posted[:30] if posted else "-",
                                "salary": salary[:50] if salary else "-",
                                "source": name,
                                "link": link,
                            })
                            print(f"  → {title} | {company} | {location}")
                    except Exception as e:
                        print(f"    [WARN] Card parse error: {e}")
                        continue

                browser.close()
                print(f"[{name}] ✓ Extracted {len(results)} jobs")
                return results

        except Exception as e:
            print(f"[{name}] Error (attempt {attempts}): {e}")
            if attempts < config.RETRY_COUNT:
                time.sleep(config.RETRY_DELAY_SEC)
            continue

    return results


def save_csv(results: list[dict], path: Path):
    """Write results to CSV."""
    lines = ["title,company,location,posted,salary,source,link"]
    for r in results:
        def esc(s):
            return (s or "").replace(",", ";").replace("\n", " ").replace("\r", "")
        lines.append(
            f'{esc(r["title"])},{esc(r["company"])},{esc(r["location"])},'
            f'{esc(r["posted"])},{esc(r["salary"])},{esc(r["source"])},{esc(r["link"])}'
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ Saved {len(results)} jobs → {path}")


def main():
    keywords = config.DEFAULT_KEYWORDS
    if len(sys.argv) > 1:
        keywords = " ".join(sys.argv[1:])

    days = config.SEARCH_DAYS
    if len(sys.argv) > len(sys.argv[1:]) + 1:
        try:
            days = int(sys.argv[-1])
        except ValueError:
            pass

    print(f"Keywords: {keywords!r}  |  Days: {days}")

    all_results = []
    for site_cfg in config.SITES:
        results = scrape_site(site_cfg["name"], site_cfg, keywords, days)
        all_results.extend(results)

    # Deduplicate by link
    seen = set()
    unique = []
    for r in all_results:
        if r["link"] and r["link"] not in seen:
            seen.add(r["link"])
            unique.append(r)

    print(f"\n=== Total unique jobs: {len(unique)} ===")
    save_csv(unique, config.OUTPUT_CSV)
    print("Done.")


if __name__ == "__main__":
    main()
