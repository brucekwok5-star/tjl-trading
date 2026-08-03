---
name: job-search
description: "Search HK job sites, handle anti-bot, manage JDs/CV/profiles, track applications in Excel."
---

# Job Search Skill

Full-stack HK job hunting workflow: scrape JobsDB / eFinancialCareers / Indeed (HK only, past 3 days), save per-job folders for your CV + cover letter, track in Excel.

## Usage

```
/job-search [keywords]
```

Example:
- `/job-search Jenkins DevOps Manager`
- `/job-search data engineer aws python`

---

## Workflow

### Step 1 — Open JobsDB in OpenClaw browser

```bash
openclaw browser open "https://hk.jobsdb.com/jobs/in-Hong-Kong?k={keywords}&daterange=3"
```

> **Anti-bot:** OpenClaw's browser is already Cloudflare-verified — the session carries over when you navigate. If a challenge appears, solve it manually, then tell me "ok".

### Step 2 — Extract via CDP evaluate

```bash
# Extract all job cards (title / company / location / posted / salary / link)
openclaw browser evaluate --fn "$(cat ~/.openclaw/skills/bkskills/job-search/scripts/jobsdb_extract.js)"

# Save result to CSV
# (I will run this automatically after extraction)
```

### Step 3 — Save JDs as folders

```bash
python3 ~/.openclaw/skills/bkskills/job-search/scripts/save_jds.py --input-csv /tmp/jobs_combined.csv
```

Creates this layout — **one folder per job** with slots for your CV and cover letter:

```
~/.openclaw/workspace/job-search/
└── JDs/
    └── JobsDB/
        └── {CompanyName}_{JobTitle}_{hash}/
            ├── job.txt           ← job details + link (auto)
            ├── cv.pdf            ← your tailored CV (you add)
            └── cover_letter.docx ← your cover letter (you add)
```

### Step 4 — Update Excel tracker

```bash
python3 ~/.openclaw/skills/bkskills/job-search/scripts/update_tracker.py --import-csv /tmp/jobs_combined.csv
```

Also runs automatically after every scrape.

---

## Anti-Bot

| Site | Method | Notes |
|------|--------|-------|
| **JobsDB** | OpenClaw browser → CDP evaluate | ✅ Session carries over between navigations |
| **eFinancialCareers** | Playwright / cloudscraper | ✅ Works |
| **Indeed** | OpenClaw browser | Solve Cloudflare manually if prompted |

---

## Config

Edit `scripts/config.py`:

```python
DEFAULT_KEYWORDS = "Jenkins DevOps"   # your search terms
SEARCH_DAYS      = 3                  # past N days (HK jobs only enforced in URL)
HK_ONLY          = True               # HK-only URL pattern on all sites
```

---

## Excel Tracker

`~/.openclaw/workspace/job-search/applications.xlsx`

| Column | Description |
|--------|-------------|
| Date Added | auto-today |
| Source | JobsDB / eFinancialCareers / Indeed |
| Job Title | from scrape |
| Company | from scrape |
| Location | from scrape |
| Salary | from scrape (if available) |
| Link | full URL |
| Status | Wishlist / Applied / Interview / Offer / Rejected |
| Applied Date | when you applied |
| Notes | your notes |

**Status colours:** Yellow=Wishlist, Blue=Applied, Green=Interview/Offer, Red=Rejected

---

## Per-Job Folder Workflow

After saving JDs:
1. Open `JDs/{Source}/{Company}_{JobTitle}_{hash}/`
2. Read `job.txt` — review the JD
3. Replace `cv.pdf` with your CV tailored for this role
4. Replace `cover_letter.docx` with your cover letter
5. In Excel tracker, update **Status** → `Applied` and set **Applied Date**
