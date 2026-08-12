# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

---

Add whatever helps you do your job. This is your cheat sheet.

## OpenClaw

### Hooks
- Always `mkdir -p ~/.openclaw/hooks` before copying hook dirs, then run `openclaw hooks enable <name>`. The enable command does NOT create the parent directory.

## 富途討論區爬蟲注意

每次運行 Futu Discussion Hunter 之前，必須確認討論區數據係今日嘅：

1. **刷新 cookies**：`openclaw browser cookies > /tmp/futu_cookies.json`
2. **檢查數據日期**：
   ```bash
   ls /tmp/futu_multi/results/ | grep "$(date +%Y%m%d)"
   ```
3. **如果冇今日數據**，必須重新運行爬蟲抓取，否則會漏報
4. **今日最新討論區**才有意義，舊數據（昨日或之前）會導致板塊被漏報

### URL 格式（重要！不同市場參數不同）

- **個股討論區**：
  - `https://q.futunn.com/nnq?stock=00700.HK&lang=zh-cn`（HK股）
  - `https://q.futunn.com/nnq?stock=TSLA.US&lang=zh-cn`（US股）
  - ⚠️ 注意：`stock_list=` 無法過濾，必須用 `stock=`
- **主討論區**：`https://q.futunn.com/nnq?lang=zh-cn`

### Playwright 爬蟲模板

```python
from playwright.sync_api import sync_playwright
import subprocess, json

def get_cookies():
    result = subprocess.run(["openclaw", "browser", "cookies"], capture_output=True, text=True, timeout=15)
    return json.loads(result.stdout)

cookies = get_cookies()
futu_cookies = [c for c in cookies if "futunn" in c.get("domain", "")]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context()
    ctx.add_cookies(futu_cookies)
    page = ctx.new_page()
    page.goto(f"https://q.futunn.com/nnq?stock={STOCK_ID}&lang=zh-cn", timeout=15000)
    page.wait_for_timeout(3500)
    for _ in range(5):
        page.keyboard.press("End")
        page.wait_for_timeout(700)
    items = page.query_selector_all(".nnq-list-item")
    # 解析每個 item...
```

## Related

- [Agent workspace](/concepts/agent-workspace)
