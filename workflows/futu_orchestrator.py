#!/usr/bin/env python3
"""
富途股票预测 — 双 Agent 调度脚本
- Agent A (本会话): 统筹分析 + 决策
- Agent B (sub-agent): Playwright 网页资料搜集
"""

import subprocess
import json
import time
import sys
import os
from datetime import datetime

WORKSPACE = "/Users/jaydensmac/.openclaw/workspace"
TMP_DIR = "/tmp/futu_orchestrator"
STATE_FILE = f"{TMP_DIR}/state.json"
STOCK_LIST_FILE = f"{TMP_DIR}/stock_list.json"

# ─── 状态读写 ───────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"phase": "init", "stocks": [], "results": {}, "log": []}

def save_state(state):
    os.makedirs(TMP_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def log(state, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    state["log"].append(line)
    print(line)

# ─── Phase 1: 获取涨幅 >10% 的股票 ──────────────────────
def phase1_get_stocks(state):
    log(state, "=== Phase 1: 读取涨幅榜 ===")
    # 读取已有股票列表，或通过简单搜索生成
    if os.path.exists(STOCK_LIST_FILE):
        with open(STOCK_LIST_FILE) as f:
            stocks = json.load(f)
        log(state, f"从文件加载 {len(stocks)} 只股票: {stocks}")
    else:
        # 默认样本（实际运行时由 Agent A 通过 browser 提取）
        stocks = [
            {"code": "00005-HK", "name": "汇丰控股", "change": "+12.3%"},
            {"code": "09988-HK", "name": "阿里巴巴", "change": "+11.5%"},
            {"code": "00772-HK", "name": "北森控股", "change": "+18.2%"},
        ]
        os.makedirs(TMP_DIR, exist_ok=True)
        with open(STOCK_LIST_FILE, "w") as f:
            json.dump(stocks, f, ensure_ascii=False)
        log(state, f"写入 {len(stocks)} 只候选股票")
    state["stocks"] = stocks
    state["phase"] = "phase2"
    save_state(state)
    return stocks

# ─── Phase 2: 启动 Agent B 爬虫 ─────────────────────────
def phase2_spawn_scraper(state, stock):
    log(state, f"=== Phase 2: 启动 Agent B 爬取 {stock['code']} ===")
    
    scraper_task = f"""你是资料搜集专家。使用 Playwright 浏览器从富途讨论区爬取股票帖文。

目标股票: {stock['code']} ({stock.get('name', '')})

执行步骤:
1. 设置 Cookie: 从 /tmp/futu_cookies.json 读取（如果没有则跳过）
2. 打开: https://www.futunn.com/hk/stock/{stock['code']}/community
3. 滚动页面 80 次（每次休息 2 秒），收集所有帖文
4. 提取: 用户名、Profile ID、发帖时间、帖文内容
5. 输出到: {TMP_DIR}/posts_{stock['code'].replace('-','_')}.json

时间转换规则:
- "分鐘前" → 当前时间减去 N 分钟
- "小時前" → 当前时间减去 N 小时
- "昨天 HH:mm" → 昨天同时刻
- "MM/dd HH:mm" → 今年该月该日

最终把结果写入 JSON 文件，格式:
{{"stock": "{stock['code']}", "posts": [{{"user": "", "profileId": "", "time_hk": "", "text": ""}}]}}

完成后报告: 已收集 N 条帖文
"""

    # 使用 openclaw sessions spawn 启动 sub-agent
    cmd = [
        "openclaw", "sessions", "spawn",
        "--label", f"futu-scraper-{stock['code']}",
        "--runtime", "subagent",
        "--task", scraper_task,
        "--cleanup", "delete"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    log(state, f"Agent B 已启动 (PID style session), output: {result.stdout[:200]}")
    state["scraper_session"] = f"futu-scraper-{stock['code']}"
    save_state(state)
    return result.stdout

# ─── Phase 3: 分析结果 ───────────────────────────────────
def phase3_analyze(state):
    log(state, "=== Phase 3: 分析帖文 ===")
    posts_file = f"{TMP_DIR}/posts_{state['stocks'][0]['code'].replace('-','_')}.json"
    
    if not os.path.exists(posts_file):
        log(state, f"文件不存在: {posts_file}，跳过分析")
        return
    
    with open(posts_file) as f:
        data = json.load(f)
    
    posts = data.get("posts", [])
    log(state, f"加载 {len(posts)} 条帖文")
    
    # 过滤逻辑
    catalyst_kw = ['業績','盈喜','制裁','禁令','訂單','AI','政策','納指','目標價','評級']
    reason_kw = ['因為','由於','預計','預期','根據','邏輯']
    
    results = []
    for p in posts:
        txt = p.get("text", "")
        if len(txt) < 30:
            continue
        if any(kw in txt for kw in catalyst_kw) or any(kw in txt for kw in reason_kw):
            results.append(p)
    
    log(state, f"过滤出 {len(results)} 条有预测价值的帖文")
    
    output = {
        "stock": state["stocks"][0]["code"],
        "total_posts": len(posts),
        "quality_posts": len(results),
        "samples": results[:5]
    }
    
    out_file = f"{TMP_DIR}/analysis_result.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(state, f"分析结果已写入: {out_file}")
    
    state["phase"] = "done"
    save_state(state)

# ─── 主循环 ──────────────────────────────────────────────
def main():
    state = load_state()
    phase = state.get("phase", "init")
    
    if phase == "init":
        stocks = phase1_get_stocks(state)
    
    if phase in ("phase2", "init"):
        stocks = state.get("stocks", phase1_get_stocks(state))
        for stock in stocks:
            phase2_spawn_scraper(state, stock)
            # 等待 sub-agent 完成（实际使用时用 sessions_yield 或轮询）
            time.sleep(2)
    
    if phase == "phase3":
        phase3_analyze(state)
    
    # 输出最终状态
    print("\n=== 最终状态 ===")
    print(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"\n日志: {len(state.get('log', []))} 条")
    for l in state.get("log", []):
        print(l)

if __name__ == "__main__":
    main()