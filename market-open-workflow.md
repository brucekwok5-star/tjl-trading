# Market Open Workflow

## 每日開盤工作流程

每個交易日開盤前/中執行：

---

## 🎯 Step 1: 查找用戶預測 (Futu Discussion Hunter)

使用 `/futu-discussion-hunter` 技能，找出持續提供高質量預測的用戶。

### 追蹤型用戶 (Profile IDs)

每次開盤前掃描這些用戶的最新發言（共19人）：

| # | 用戶名 | Profile ID | 專長 | 狀態 |
|---|--------|-----------|------|------|
| 1 | 杭州吕布 | 18099215 | AI存儲/半導體 | ⏳ |
| 2 | 嘉运久赢 | 27406798 | 港股/A股 並購 | ⏳ |
| 3 | 用爱感动A股 | 22379942 | 碳化矽/新經濟 | ⏳ |
| 4 | 万花美偲 | 36078245 | AI/工業智能 | ⏳ |
| 5 | Hanchiller | 26136151 | 韓股槓桿 | ⏳ |
| 6 | 人B 失格 | 14042366 | 比特幣/加密 | ⏳ |
| 7 | 我不是沈大师 | 51831066 | 宏觀/大宗商品 | ⏳ |
| 8 | CMOCC | 35482103 | 兆易/半導體 | ⏳ |
| 9 | 東海帝王 | 35482104 | 技術分析 | ⏳ |
| 10 | (歷史) | 231473840 | 智譜/AI | ✅命中 |
| 11 | (歷史) | 231721959 | 天岳先進 | ✅命中 |
| 12 | (歷史) | 21437959 | 天岳先進 | ✅命中 |
| 13 | (歷史) | 7086101 | 思科 | ✅命中 |
| 14-19 | 其他 | ... | 港股/A股 | ⏳ |

### 快速掃描全部用戶

```bash
# 從 CSV 加載並逐一掃描
python3 /tmp/scan_all_profiles.py
```

**輸出**：預測型用戶列表 → `futu_predictive_users.csv`

---

## 🎯 Step 2: 找投資機會 (Futu Discussion Hunter)

使用 `/futu-discussion-hunter` 技能，掃描目標股票討論區。

### 熱門股票列表

每次掃描這些：
- **龍頭**: 00700-HK, 09988-HK, 03690-HK
- **半導體**: 00981-HK, 01347-HK, 00700-HK
- **AI/科技**: TSLA-US, NVDA-US, GOOG-US
- **高波動**: ALB-US, PDD-US, BILI-US

### 過濾邏輯
- ❌ 純目標價無原因 → 跳過
- ❌ 事後分析文 → 跳過
- ✅ 有催化劑 + 有邏輯 → 記錄
- ✅ 在大漲前發布 → 重點追蹤

### 輸出格式

| 用戶名 | 發佈時間 | 股票 | 摘要 | 狀態 |
|--------|----------|------|------|------|
| @xxx | HH:MM | 00700-HK | 因為XXX所以YYY | ⏳ 待驗證 |

---

## 🎯 Step 3: 計算止損線 (Trailing Stop)

使用 `/trailing-stop` 技能，計算持倉的日內止損線。

### 持倉清單

傳入持倉股票：
```
/trailing-stop 700 1357 1428 2840 2883 2899 GOOG ALB PDD TSLA
```

### 計算公式
```
日內止損% = 近30日平均日振幅 × 2倍安全係數

止損線 = 今日高點 × (1 - 日內止損%)
```

### 止損參照表

| 股票類型 | 平均日振幅 | 止損% | 說明 |
|---------|-----------|--------|------|
| ETF/藍籌 | 1-2% | 5-7% | 低波動 |
| 科技股 | 3-5% | 8-10% | 中波動 |
| 汽車/鋰業 | 5%+ | 10-12% | 高波動 |
| 妖股/小盤 | 8%+ | 12-15% | 極高波動 |

### 設置提醒
在 Futu app 設置價格提醒：
- 進入股票詳情頁 → 點擊 🔔 鈴鐸
- 設置「價格低於」止損線
- 開啟通知

---

## 🎯 Step 4: 持倉分析 (Stock Analysis)

使用 `/stock-analysis-hk` 或 `/stock-analysis-us` 技能分析持倉。

### HK 股分析
```bash
/stock-analysis-hk 00700-HK --signals
```

### US 股分析
```bash
/stock-analysis-us TSLA-US --signals
```

### 分析內容
- **趨勢**: RSI, MACD, EMA
- **信號**: 買入/賣出/觀望
- **支撐/阻力**: 關鍵價位
- **成交量**: 異常放大/萎縮

---

## 📋 完整工作流示例

```
# === 開盤前 9:15 ===

# 1. 掃描預測型用戶
/futu-discussion-hunter 18099215
/futu-discussion-hunter 27406798
/futu-discussion-hunter 36078245

# 2. 掃描熱門股票機會
/futu-discussion-hunter 00981-HK
/futu-discussion-hunter 00700-HK
/futu-discussion-hunter TSLA-US

# 3. 計算止損線
/trailing-stop 700 1357 2840 GOOG PDD TSLA

# 4. 技術分析
/stock-analysis-hk 00700-HK --signals
/stock-analysis-us TSLA-US --signals
```

---

## ⚡ 快速指令速查

| 步驟 | 技能 | 指令 |
|------|------|------|
| 1-2 | futu-discussion-hunter | `/futu-discussion-hunter [股票或Profile]` |
| 3 | trailing-stop | `/trailing-stop [股票代碼]` |
| 4 | stock-analysis-hk | `/stock-analysis-hk [代碼] --signals` |
| 4 | stock-analysis-us | `/stock-analysis-us [代碼] --signals` |

---

## 📁 輸出文件

- `futu_predictive_users.csv` → 預測型用戶記錄
- `futu_XXX_posts.json` → 爬取的帖子
- `market-open-workflow.md` → 本工作流文檔