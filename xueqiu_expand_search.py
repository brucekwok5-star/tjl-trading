#!/usr/bin/env python3
"""Quick Xueqiu user expansion - 5 terms only"""
import subprocess, json, re, time
from playwright.sync_api import sync_playwright

# Search terms — module-level so tests can introspect
terms = ["港股投資達人", "炒股致富", "基金經理", "分析師", "李大霄"]
SEARCH_TERMS = terms  # alias for newer code

# Output path for collected user IDs — module-level so tests can verify
OUTPUT_PATH = "/tmp/xueqiu_user_ids.txt"
# Legacy path retained for back-compat with existing tests / consumers.
LEGACY_OUTPUT_PATH = "/tmp/xueqiu_expanded_users.json"


def get_cookies():
    """Return list of cookies whose domain contains 'xueqiu' and which have a value."""
    try:
        r = subprocess.run(["openclaw", "browser", "cookies"], capture_output=True, text=True, timeout=15)
        cookies_data = json.loads(r.stdout)
    except Exception:
        return []
    return [c for c in cookies_data if "xueqiu" in c.get("domain", "") and c.get("value")]


def _extract_user_ids(html):
    """Extract xueqiu user IDs from search-result HTML using two regex orderings."""
    ids = re.findall(r'href="/(\d{7,10})"[^>]*class="[^"]*user-name[^"]*"', html)
    ids += re.findall(r'class="user-name[^"]*"[^>]*href="/(\d{7,10})"', html)
    return list(set([int(x) for x in ids if int(x) > 1e6]))


def run_search(terms=None, headless=True, output_path=None):
    """Run the search-and-extract loop. Returns the set of collected user IDs."""
    terms = terms if terms is not None else SEARCH_TERMS
    output_path = output_path if output_path is not None else OUTPUT_PATH
    cookies = get_cookies()
    all_ids = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        ctx.add_cookies(cookies)
        page = ctx.new_page()
        for term in terms:
            url = f"https://xueqiu.com/k?q={term.replace(' ', '%20')}"
            print(f"Searching: {term}", end=" ")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=10000)
                time.sleep(3)
                html = page.content()
                ids = _extract_user_ids(html)
                print(f"→ {len(ids)} users")
                all_ids.update(ids)
                time.sleep(0.5)
            except Exception as e:
                print(f"Error: {e}")
        page.close()
        browser.close()
    print(f"\n=== Total: {len(all_ids)} users ===")
    try:
        with open(output_path, "w") as f:
            f.write("\n".join(str(x) for x in sorted(all_ids)))
        # Legacy path for back-compat
        try:
            with open(LEGACY_OUTPUT_PATH, "w") as f:
                f.write("\n".join(str(x) for x in sorted(all_ids)))
        except Exception:
            pass
    except Exception as e:
        print(f"Could not write {output_path}: {e}")
    return all_ids


if __name__ == "__main__":
    run_search()