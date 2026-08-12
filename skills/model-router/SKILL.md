---
name: model-router
description: Use when deciding which model (MiniMax or GLM) to route a task to. Auto-selects by task type, cost tier, time-of-day, and real-time usage.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
metadata:
  hermes:
    tags: [model-selection, minimax, glm, routing, cost-optimization, performance, off-peak]
    related_skills: [minimax-usage-checker]
---

# Model Router

Auto-select MiniMax or GLM (Z.AI) for every task based on: task type, cost tier, time-of-day off-peak windows, and real-time usage signals.

## Off-Peak vs Peak Windows

### Z.AI (Zhipu AI)
| Window | Hours (HK/SGT UTC+8) | Rate |
|--------|----------------------|------|
| **Off-peak** | Mon–Fri 00:00–14:00, 18:00–24:00 | **50% off** (0.5× standard) |
| **Peak** | Mon–Fri **14:00–18:00** | Standard rate |

### MiniMax
| Window | Hours (HK UTC+8) | Rate |
|--------|-----------------|------|
| Off-peak | All day | Standard rate (no discount) |
| Peak | Mon–Fri **15:00–17:30** | Rate-limiting active (not price change) |

**Implication:** Route heavy Z.AI usage to off-peak windows (before 14:00 or after 18:00 weekdays, all day weekends) for 50% savings. Avoid heavy MiniMax tasks during 15:00–17:30.

## Model Hierarchy

### Capability Ranking
GLM-5 > MiniMax-M3 > MiniMax-M2.7 > GLM-4.5-Air > GLM-4-FlashX > GLM-4.7-Flash

### Cost Ranking — Standard Rates (input tokens)
GLM-5 > MiniMax-M3 > MiniMax-M2.7 > GLM-4.5-Air > GLM-4-FlashX > GLM-4.7-Flash
¥4–6/M > ¥2.10–4.20/M > ¥2.10/M > ¥0.80/M > ¥0.10/M > **FREE**

### Cost Ranking — Z.AI Off-Peak (50% off)
GLM-5 > GLM-4.5-Air > GLM-4-FlashX
¥2–3/M > ¥0.40/M > ¥0.05/M

| Tier | Model | Standard in | Off-peak in | Notes |
|------|-------|------------|-------------|-------|
| T0 | **GLM-5** | ¥4–6/M | ¥2–3/M | Most capable |
| T1 | **MiniMax-M3** | ¥2.10–4.20/M | ¥2.10–4.20/M | No time discount |
| T2 | **MiniMax-M2.7** | ¥2.10/M | ¥2.10/M | No time discount |
| T3 | **GLM-4.5-Air** | ¥0.80/M | ¥0.40/M | Off-peak = 1/5 cost of M2.7 |
| T4 | **GLM-4-FlashX** | ¥0.10/M | ¥0.05/M | |
| T5 | **GLM-4.7-Flash** | **FREE** | **FREE** | Always free |

## Current Plans

| Provider | Plan | Monthly | Notes |
|----------|------|---------|-------|
| Z.AI | Lite | ¥118/mo | Batch API = additional 50% off on top of off-peak |
| MiniMax | Plus | ¥45/mo | Drains hourly/weekly. Renews ~2026-08-18. 56% hourly, 26% weekly used. |

## Routing Decision Tree

```
Is Z.AI off-peak window active? (Mon–Fri 00:00–14:00 or 18:00–24:00, or all day Sat/Sun)
  YES → Route all capable tasks to Z.AI GLM models (50% savings vs peak)
  NO  → Is it peak hours 14:00–18:00 on a weekday?
         YES → Prefer MiniMax or GLM-4.7-Flash (free) during peak

Is the task simple?
  (greeting, one-liner, fact lookup, define X, unit conversion)
  → GLM-4.7-Flash (FREE always — day/night doesn't matter)

Does it need strong reasoning or code?
  → MiniMax-M2.7 — flat rate, no peak surcharge, and MiniMax rate-limits during 15:00–17:30 anyway
  → During off-peak: also consider GLM-5 (¥2–3/M off-peak vs ¥4–6 peak)

Does it need GLM-5's specific capabilities?
  → GLM-5 — use off-peak if possible (¥2–3/M vs ¥4–6/M peak)

Does it need long context (>512k tokens)?
  → MiniMax-M3 (¥2.10/M for ≤512k; ¥4.20/M for >512k)

Is it a cron/batch task?
  → Schedule for Z.AI off-peak window to stack 50% off-peak + 50% batch = 75% off
  → Or use MiniMax outside 15:00–17:30 to avoid rate-limiting

Is MiniMax hourly quota >80% used?
  → Route to GLM-4.7-Flash for non-critical tasks

Is MiniMax weekly quota >80% used?
  → GLM off-peak for everything except hard reasoning

Did a MiniMax call return 402/429/403?
  → Switch to GLM-4.7-Flash immediately
```

## Time-of-Day Quick Reference (HK/SGT UTC+8)

```
MON–FRI
  00:00–14:00  → Z.AI off-peak 50% off + MiniMax OK
  14:00–15:00  → Z.AI peak (full rate) + MiniMax starting to tighten
  15:00–17:30  → Z.AI peak + MiniMax rate-limiting — avoid heavy MiniMax
  17:30–18:00  → Z.AI peak (last 30min) + MiniMax easing
  18:00–24:00  → Z.AI off-peak 50% off + MiniMax OK

SAT–SUN  → Z.AI off-peak all day (50% off) + MiniMax all clear (no rate-limiting)
```

## Batch API — Stack with Off-Peak for 75% Off

Z.AI Batch API = 50% off standard. During off-peak = additional 50% off on top.
**Net effect: 25% of standard rate.**

Use for: cron job outputs (TJL scan summaries, reports, bulk processing).

## Model Switching Commands

```
/model glm              → GLM-5 for this session
/model minimax          → MiniMax-M2.7 for this session
/model minimax-m3       → MiniMax-M3 for this session
/model glm-flash        → GLM-4-FlashX for this session
/model minimax --global → persist MiniMax-M2.7 as default
/model glm --global     → persist GLM-5 as default
```

## Task-Type Quick Reference

```
GLM-5 (flagship — use off-peak for 50% savings):
  - Tasks requiring most capable GLM model

MiniMax-M3 (most capable MiniMax):
  - Complex reasoning beyond M2.7
  - Long context >512k tokens

MiniMax-M2.7 (reasoning/code — no time discount, no peak surcharge):
  - Complex debugging / root-cause analysis
  - Multi-file code changes or architecture
  - Planning workflows or PR strategies
  - Long document synthesis (>5 sections)
  - Math/statistics reasoning
  - Note: avoid heavy use 15:00–17:30 due to rate-limiting

GLM-4.5-Air (mid-tier — cheapest capable model off-peak):
  - Off-peak: ¥0.40/M in — best value for capable tasks
  - Peak: ¥0.80/M in — still cheap vs MiniMax

GLM-4-FlashX (cheap):
  - Off-peak: ¥0.05/M in — very cheap

GLM-4.7-Flash (FREE — default for everything simple):
  - Always free regardless of time
  - Default for greetings, lookups, short drafts, brainstorming
```

## Quota-Aware Overrides

1. **MiniMax hourly >80%** — avoid MiniMax for non-critical tasks until reset (~50min from each hour).
2. **MiniMax weekly >80%** — conservatively route to GLM off-peak.
3. **402/429/403 error** — immediately switch to GLM-4.7-Flash and log the failure mode.

## Anti-Patterns

1. **Never pay peak rate for Z.AI when off-peak is available** — 50% savings stacks with batch API for 75% off.
2. **Never use MiniMax for heavy tasks during 15:00–17:30** — rate-limiting kicks in; off-peak is free.
3. **Never use GLM-5 for simple queries** — GLM-4.7-Flash is free; save GLM-5 for when its capability is genuinely needed.
4. **Never ignore 402/429 errors** — quota exhausted; switch to GLM-4.7-Flash.

## Completion Criteria

- [ ] Task completed successfully on the chosen model
- [ ] No quota errors (402/429) were triggered
- [ ] If a 402/429 occurred, retry on GLM-4.7-Flash succeeded
- [ ] Cheapest model with sufficient capability was used at the best time window
