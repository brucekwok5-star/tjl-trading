# 富途讨论区预测型机会发掘工作流

## 目标
从富途港股涨幅榜中，发现今日涨幅 >10% 的股票 → 追溯上涨催化剂 → 找出在大涨前发布有逻辑、有催化剂预测的用户 → 扫描该用户 Profile 发现未发生的未来机会。

## 前置条件
- 富途账号已登录（Cookie 存储于 `/tmp/futu_cookies.json`）
- Python Playwright 已安装
- `openclaw` CLI 可用

---

## 第一阶段：发现涨幅 >10% 的股票

### 步骤 1.1 — 打开富途成交额榜
```bash
openclaw browser open "https://www.futunn.com/quote/hk/stock-list/all-hk-stocks/top-turnover"
```

### 步骤 1.2 — 提取涨幅 >10% 的股票
```javascript
// 在富途页面执行
(function() {
    var rows = document.querySelectorAll("table tbody tr");
    var result = [];
    rows.forEach(function(row) {
        var cells = row.querySelectorAll("td");
        if (cells.length >= 7) {
            var name = cells[2] && cells[2].textContent ? cells[2].textContent.trim() : "";
            var code = cells[1] && cells[1].textContent ? cells[1].textContent.trim() : "";
            var changePct = cells[5] && cells[5].textContent ? cells[5].textContent.trim() : "";
            if (name && code && changePct) {
                var pct = parseFloat(changePct.replace("%","").replace("+",""));
                if (!isNaN(pct) && pct > 10) {
                    result.push(name + "|" + code + "|" + changePct);
                }
            }
        }
    });
    return result;
})()
```

### 步骤 1.3 — 记录上涨时间线（通过新闻搜索）
```bash
# 对每只涨幅 >10% 的股票搜索今日催化剂
web_search "股票名 代码 5月22日 涨幅 原因"
web_fetch "<新闻URL>" 获取详细催化剂和时间点
```

### 步骤 1.4 — 汇总上涨原因
对每只股票记录：
| 字段 | 说明 |
|------|------|
| 股票名称/代码 | |
| 收盘涨幅 | |
| 催化剂 | 业绩公告 / 指数纳入 / 政策 / 产品发布 等 |
| 大概上涨时段 | 早市 / 午后 / 全天 |

---

## 第二阶段：搜索讨论区预测帖

### 步骤 2.1 — 导出 Cookie
```bash
openclaw browser cookies > /tmp/futu_cookies.json
```

### 步骤 2.2 — 对每只股票运行讨论区爬虫
```python
#!/usr/bin/env python3
"""Futu discussion scraper"""
import json
from datetime import datetime, timedelta
import pytz
from playwright.sync_api import sync_playwright

STOCK_CODE = "XXXXX-HK"   # <-- 替换为实际代码
COOKIE_FILE = "/tmp/futu_cookies.json"
OUTPUT_FILE = f"/tmp/futu_{STOCK_CODE.replace('-','_')}_posts.json"
HK_TZ = pytz.timezone("Asia/Hong_Kong")

JS = """
function() {
    var r = [];
    document.querySelectorAll("a[href*='/feed/']").forEach(function(a) {
        var c = a.closest('[class*="item"]') || a.closest('[class*="post"]') ||
                a.closest('[class*="comment"]') || a.closest('[class*="feed"]') || a.parentElement;
        if (!c) return;
        var t = a.innerText.trim();
        var profileId = '';
        var p = c.querySelector("a[href*='/profile/']");
        if (p) {
            var m = p.href.match(/\\/profile\\/(\\d+)/);
            if (m) profileId = m[1];
        }
        var u = profileId || 'anonymous';
        var txt = '';
        var sels = ['[class*="content"]','[class*="text"]','[class*="desc"]','[class*="article"]'];
        for (var i=0; i<sels.length; i++) {
            var el = c.querySelector(sels[i]);
            if (el && el.innerText.trim()) { txt = el.innerText.trim(); break; }
        }
        if (!txt) { txt = c.innerText.replace(t,'').trim(); if (u!=='anonymous') txt=txt.replace(u,'').trim(); }
        txt = txt.replace(/\\s+/g,' ').slice(0,300);
        r.push({time:t, user:u, profileId:profileId, profileUrl:profileId ? 'https://q.futunn.com/profile/' + profileId : '', text:txt});
    });
    return r;
}
"""

def convert_to_hk(s):
    now = datetime.now(HK_TZ)
    if any(x in s for x in ['分鐘前','分前']):
        m = int(s.replace('分鐘前','').replace('分前','').strip())
        return (now - timedelta(minutes=m)).strftime('%Y-%m-%d %H:%M HKT')
    if any(x in s for x in ['小時前']):
        h = int(s.replace('小時前','').strip())
        return (now - timedelta(hours=h)).strftime('%Y-%m-%d %H:%M HKT')
    if '昨天' in s:
        y = now - timedelta(days=1)
        parts = s.split('昨天')
        tp = parts[1].strip() if len(parts)>1 else ''
        if tp:
            try:
                t = datetime.strptime(tp, '%H:%M')
                return y.replace(hour=t.hour, minute=t.minute).strftime('%Y-%m-%d %H:%M HKT')
            except: return f"{y.strftime('%Y-%m-%d')} {tp} HKT"
        return y.strftime('%Y-%m-%d')
    if '/' in s and ':' not in s:
        try:
            parts = s.strip().split()
            m,d = parts[0].split('/')
            tp = parts[1] if len(parts)>1 else '00:00'
            return now.replace(month=int(m), day=int(d), hour=int(tp.split(':')[0]), minute=int(tp.split(':')[1])).strftime('%Y-%m-%d %H:%M HKT')
        except: return f"{s} HKT"
    if '-' in s and ':' in s:
        try:
            dt = datetime.strptime(s.replace('/','-'), '%Y-%m-%d %H:%M')
            return HK_TZ.localize(dt).strftime('%Y-%m-%d %H:%M HKT')
        except: return f"{s} HKT"
    return f"{s} HKT"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context()
    with open(COOKIE_FILE) as f:
        for c in json.load(f):
            if 'futunn' in c.get('domain',''):
                try: ctx.add_cookies([c])
                except: pass
    page = ctx.new_page()
    page.goto(f"https://www.futunn.com/hk/stock/{STOCK_CODE}/community", timeout=120000, wait_until="domcontentloaded")
    all_posts, seen, sc = [], set(), 0
    while sc < 80:
        page.evaluate("window.scrollBy(0,600)")
        page.wait_for_timeout(2000)
        sc += 1
        posts = page.evaluate(JS)
        nc = 0
        for pp in posts:
            k = pp['time']+'|'+pp['user']+'|'+pp['text'][:50]
            if k not in seen:
                seen.add(k)
                all_posts.append({'time':pp['time'],'time_hk':convert_to_hk(pp['time']),'user':pp['user'],'profileId':pp.get('profileId',''),'profileUrl':pp.get('profileUrl',''),'text':pp['text']})
                nc += 1
        if sc > 10 and nc == 0: break
    with open(OUTPUT_FILE,'w') as f:
        json.dump({'stock':STOCK_CODE,'posts':all_posts},f,ensure_ascii=False,indent=2)
    print(f"Done: {len(all_posts)} posts")
    browser.close()
```

### 步骤 2.3 — 分析预测帖
```python
#!/usr/bin/env python3
"""分析爬取的帖子，过滤出有逻辑的预测"""
import json, sys

STOCK = sys.argv[1] if len(sys.argv) > 1 else "XXXXX-HK"
try:
    with open(f"/tmp/futu_{STOCK.replace('-','_')}_posts.json") as f:
        d = json.load(f)
except:
    print(f"文件不存在"); exit(1)

posts = d['posts']

# 催化剂关键词
catalyst_kw = [
    '業績','財測','盈喜','盈警','beat','miss',
    '制裁','禁令','出口','實體清單','ban',
    '訂單','contract','supply','漲價','加價',
    'AI','算力','服務器','設備','fab','產能',
    '政策','補貼','補貼','subsidy',
    '放量','突破','technical',
    '分析師','目標價','評級','rating','target',
    '北水','南下','港股通','納入','指數','index',
    '大摩','摩根','Morgan','MS','高盛','Goldman',
    'IPO','上市','財報','季度','年報',
]

# 逻辑关键词
reason_kw = [
    '因為','由於','所以','根據',
    '預計','預期','估計','相信','將會','有望',
    'logic','because','since','due to',
    '顯示','表明','反映',
    '考慮到','基於','依據',
]

skip_kw = ['專欄','Alpha Call','Podcast','覆盤','早盘策略','盤後分析','直播回顧','摩帥']

seen = set()
results = []

for p in posts:
    u = p['user'].strip()
    t = p.get('time_hk', p['time']).strip()
    txt = p['text'].strip()
    if not u or u == 'unknown' or len(txt) < 30: continue
    if txt in ['評論了股票','發表了文章','參與了話題','分享了','查看更多評論...']: continue
    if any(kw in txt[:30] for kw in skip_kw): continue
    has_cat = any(kw in txt for kw in catalyst_kw)
    has_reason = any(kw in txt for kw in reason_kw)
    if has_cat or has_reason:
        key = txt[:80]
        if key not in seen:
            seen.add(key)
            results.append(p)
            print(f"=== @{u} [{t}] ===")
            print(txt[:500])
            print()

print(f"\n=== SUMMARY: {d['stock']} | 总帖数: {len(posts)} | 优质候选: {len(results)} ===")
```

---

## 第三阶段：识别有效预测并录入CSV

### 步骤 3.1 — 判断标准
有效的预测必须满足：
1. **发帖时间早于股价大涨**（至少早1小时，越早越有价值）
2. **包含具体催化剂**（业绩、指数纳入、IPO、政策、订单等）
3. **有逻辑推理**（"因为X，所以Y会涨"而非纯喊目标价）

### 步骤 3.2 — 更新预测追踪CSV
```python
import csv

CSV_FILE = "/Users/jaydensmac/.openclaw/workspace/futu_predictive_users.csv"

new_entry = {
    '用户名': '<Profile ID>',
    '用户名称': '<用户名显示名>',
    '信息时间 (HKT)': '<发帖时间>',
    '信息内容': '<预测内容摘要>',
    '预测正确与否': '✅ 已命中：<实际涨幅> | ⏳ 待验证',
    '直接链接': 'https://q.futunn.com/profile/<Profile ID>'
}

with open(CSV_FILE, 'a', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['用户名','用户名称','信息时间 (HKT)','信息内容','预测正确与否','直接链接'])
    writer.writerow(new_entry)
```

---

## 第四阶段：从高质量用户 Profile 中发掘未来机会

本阶段的核心思路：**以用户为锚点**，而非以股票为锚点。先从 CSV 中筛选出有预测历史（已命中或待验证）的高质量用户，再逐个扫描其 Profile，从其关注列表和发言历史中提炼出尚未被市场定价的股票机会。

### 步骤 4.1 — 从 CSV 筛选高质量用户

从 `futu_predictive_users.csv` 中提取 Top 用户：

```python
import csv

CSV_FILE = "/Users/jaydensmac/.openclaw/workspace/futu_predictive_users.csv"

with open(CSV_FILE) as f:
    rows = list(csv.DictReader(f))

# 打分：✅命中 = 2分，⏳待验证 = 1分，按用户去重
seen_users = {}
for r in rows:
    link = r.get('直接链接','')
    if not link or link == '直接链接': continue
    uid = r.get('用户名','')
    status = r.get('预测正确与否','')
    score = 2 if status.startswith('✅') else 1 if '⏳' in status else 0
    # 同用户保留最高分
    if uid not in seen_users or seen_users[uid] < score:
        seen_users[uid] = score

# 排序输出 Top N
for uid, score in sorted(seen_users.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"{uid} | 得分: {score} | https://q.futunn.com/profile/{uid}")
```

**评分标准：**
- ✅ 已命中（历史预测兑现）→ 2分 → 强信任
- ⏳ 待验证（逻辑好但结果未出）→ 1分 → 观察
- ❌ 未中 → 0分 → 不纳入

### 步骤 4.2 — 打开用户 Profile

按评分从高到低，逐个打开用户主页：
```bash
openclaw browser open "https://q.futunn.com/profile/<Profile ID>"
```

> **注意：** 多个用户可同时开 Tab，但避免超过 3 个导致页面卡顿

### 步骤 4.3 — 等待页面加载
```bash
openclaw browser wait --time 5000
```

### 步骤 4.4 — 提取 Profile 中所有提及的股票
```javascript
(function() {
    var posts = [];
    var links = document.querySelectorAll("a[href*='/stock/']");
    links.forEach(function(a) {
        var text = a.innerText.trim();
        var href = a.href;
        if (text && text.length > 3 && text.length < 80) {
            posts.push(text + " | " + href);
        }
    });
    return posts.slice(0, 60);
})()
```

### 步骤 4.5 — 去重 + 过滤候选股

从结果中提取并去重，过滤规则：

| 过滤类型 | 处理方式 |
|---------|---------|
| 指数 ETF（恒生指数、纳斯达克综合、标普500等） | 排除 |
| 杠杆 ETF（2倍做多、3倍做空等） | 排除（除非用户专门做这个赛道）|
| 只有股票名称无代码 | 排除 |
| 代码重复 | 去重，保留第一次出现 |
| 保留 | 港股 (XXXXX-HK)、美股 (XXXXX-US) |

```python
def filter_stocks(raw_results):
    exclude_patterns = ['恒生指數','納斯達克','標普500','道瓊斯','日經225',
                        '指數期貨','指數ETF','QQQ','SPX','DJI','KOSPI','N225']
    exclude_suffix = ['-2X','-3X','2X','3X','2倍','3倍','2x','3x',
                     'ETF-Invesco','ETF-Direxion','ETF-Tradr']
    
    seen = set()
    results = []
    for item in raw_results:
        name, url = item.split(' | ')
        code_match = url.split('/stock/')[1].split('?')[0] if '/stock/' in url else ''
        
        # Skip if code already seen
        if code_match in seen:
            continue
        
        # Skip if matches exclude patterns
        skip = False
        for pat in exclude_patterns + exclude_suffix:
            if pat.lower() in name.lower():
                skip = True
                break
        if skip:
            continue
        
        # Must have HK or US suffix with code
        if not any(suffix in code_match for suffix in ['-HK','-US']):
            continue
        
        seen.add(code_match)
        results.append({'name': name, 'code': code_match, 'url': url})
    
    return results
```

### 步骤 4.6 — 评估每只股票的未来机会

对每只候选股，判断是否属于"还未发生的催化剂"：

| 信号类型 | 说明 | 置信度 |
|---------|------|--------|
| 分析师覆盖/目标价（尚未到时间节点） | 大行研报目标价，事件未兑现 | ⭐⭐⭐ |
| 指数纳入预期（结果未公布） | 季检前潜伏，纳入即暴涨 | ⭐⭐⭐ |
| IPO/上市催化（公司即将上市） | 关联公司持股受益 | ⭐⭐ |
| 政策预期 | 补贴/开放场景等尚未落地 | ⭐⭐ |
| 纯目标价，无逻辑 | 无实质催化剂，不采纳 | ❌ |
| 正在发生的热点（已涨过） | 追热点非预测，谨慎 | ⭐ |

### 步骤 4.7 — 汇总输出未来机会清单

```
## [日期] 用户 Profile 未来机会

### 高置信度用户来源
| 用户 | Profile ID | 信任得分 | 主要关注赛道 |
|------|-----------|---------|------------|
| 用户A | 12245320 | ⭐⭐⭐ | 18C/AI大模型 |
| 用户B | 13725611 | ⭐⭐ | SiC/半导体 |

### 未来机会清单
| 置信度 | 股票 | 代码 | 来源用户 | 催化剂逻辑 | 备注 |
|--------|------|------|---------|-----------|------|
| ⭐⭐⭐ | 天数智芯 | 09903.HK | 12245320 | 国家级算力独角兽，目标$600，尚未兑现 | |
| ⭐⭐⭐ | Cerebras | CBRS.US | 18099215 | AI算力芯片，估值严重低估 | |
| ⭐⭐ | Wolfspeed | WOLF.US | 13725611 | SiC全球龙头，A股映射逻辑 | |
```

### 步骤 4.8 — 更新监控列表

将高置信度机会写入 `futu_watchlist.md`，持续跟踪：

```markdown
# 富途预测用户 — 未来机会监控列表

## 更新日期：2026-05-22

### ⭐⭐⭐ 强推荐（已有催化剂逻辑支撑）
| 股票 | 代码 | 来源用户 | 催化剂 | 目标逻辑 |
|------|------|---------|-------|---------|
| 天数智芯 | 09903.HK | 12245320 | 国家级算力独角兽 | 目标$600，空间大 |
| Cerebras | CBRS.US | 18099215 | AI算力芯片 | 估值低估，IPO后暴涨 |

### ⭐⭐ 推荐
| 股票 | 代码 | 来源用户 | 催化剂 | 备注 |
|------|------|---------|-------|------|
| Wolfspeed | WOLF.US | 13725611 | SiC全球映射 | 跟涨美股映射A股 |
```

存储路径：`/Users/jaydensmac/.openclaw/workspace/futu_watchlist.md`

---

## 输出格式

### 每日总结报告
```
## [日期] 涨幅 >10% 预测追踪

### 涨幅榜
| 股票 | 代码 | 涨幅 | 催化剂 | 上涨时段 |

### 预测命中
| 用户 | Profile ID | 发帖时间 | 预测内容 | 实际结果 | 状态 |

### 用户Profile未来机会
| 用户 | Profile Link | 股票 | 代码 | 逻辑 | 置信度 |
```

### CSV 字段（追加到 futu_predictive_users.csv）
| 列 | 说明 |
|---|---|
| 用户名 | Futu Profile ID |
| 用户名称 | 显示名 |
| 信息时间 (HKT) | 香港时间 |
| 信息内容 | 原始预测内容摘要 |
| 预测正确与否 | ✅命中 / ⏳待验证 / ❌未中 |
| 直接链接 | https://q.futunn.com/profile/ID |

---

## 注意事项
- 每次只并行运行 2~3 个爬虫，避免页面超时
- 爬虫超时用 `--timeout 120000` 并在独立进程运行
- Profile 扫描时需要等待页面完全加载（等待 5 秒）
- 去重后保留唯一股票代码，避免重复信息干扰判断
