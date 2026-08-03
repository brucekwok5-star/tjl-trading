"""
Configuration for job-search skill.
Edit these values to customise behaviour.
"""

import pathlib

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME = pathlib.Path.home()
WORKSPACE_DIR = HOME / ".openclaw" / "workspace" / "job-search"
JD_DIR = WORKSPACE_DIR / "JDs"
CV_DIR = WORKSPACE_DIR / "CV"
OUTPUT_CSV = pathlib.Path("/tmp/jobs_combined.csv")
COOKIE_FILE = pathlib.Path("/tmp/job_search_cookies.json")
EXCEL_PATH = WORKSPACE_DIR / "applications.xlsx"
CV_PROFILE_PATH = WORKSPACE_DIR / "CV_PROFILE.md"

# ---------------------------------------------------------------------------
# Search defaults
# ---------------------------------------------------------------------------
DEFAULT_KEYWORDS = "Jenkins DevOps"
SEARCH_DAYS = 3   # past N days
HK_ONLY = True       # enforce Hong Kong jobs only

# ---------------------------------------------------------------------------
# Sites  (name, base_url, search_param_name)
# ---------------------------------------------------------------------------
SITES = [
    {
        "name": "JobsDB",
        "url": "https://hk.jobsdb.com/jobs/in-Hong-Kong?k={keywords}&daterange={days}",
        "title_sel": ["[class*='title'] a", "h1 a", "a[href*='/job/']"],
        "company_sel": ["[class*='company']", "[class*='employer']"],
        "location_sel": ["[class*='location']", "[class*='area']"],
        "posted_sel": ["[class*='date']", "[class*='posted']", "span[data-test='post-date']"],
        "salary_sel": ["[class*='salary']", "[class*='compensation']"],
        "link_sel": "a[href*='/job/']",
        "link_prefix": "https://hk.jobsdb.com",
        "job_card_sel": ["[class*='job-card']", "[class*='result-item']", "article"],
    },
    {
        "name": "eFinancialCareers",
        "url": "https://www.efinancialcareers.hk/jobs/{keywords}/in-hong-kong?q={keywords}&filters.postedDate=THREE",  # HK enforced in URL
        "title_sel": ["[class*='job-title']", "h2 a", "a[href*='/job/']"],
        "company_sel": ["[class*='company-name']", "[class*='company']"],
        "location_sel": ["[class*='location']", "[class*='area']"],
        "posted_sel": ["[class*='date']", "[class*='posted']"],
        "salary_sel": ["[class*='salary']", "[class*='compensation']"],
        "link_sel": "a[href*='/job/']",
        "link_prefix": "https://www.efinancialcareers.hk",
        "job_card_sel": ["[class*='job-search-result']", "article", "[class*='result-item']"],
    },
    {
        "name": "Indeed",
        "url": "https://hk.indeed.com/jobs?q={keywords}&l=Hong+Kong&sort=date&fromage={days}",
        "title_sel": ["[class*='title']", "h2 a", "a[href*='/rc/clk']"],
        "company_sel": ["[class*='company']", "[class*='companyName']"],
        "location_sel": ["[class*='location']", "[class*='area']", "[class*='geo']"],
        "posted_sel": ["[class*='date']", "[class*='result-link'] span"],
        "salary_sel": ["[class*='salary']", "[class*='estimated-salary']"],
        "link_sel": "a[href*='/rc/clk'], a[href*='/viewjobs']",
        "link_prefix": "https://hk.indeed.com",
        "job_card_sel": [".job-card", "[data-jobid]", ".jobsearch-ResultsContainer li"],
    },
]

# ---------------------------------------------------------------------------
# Anti-bot settings
# ---------------------------------------------------------------------------
RETRY_COUNT = 3
RETRY_DELAY_SEC = 5
HUMAN_DELAY_MIN = 1.5
HUMAN_DELAY_MAX = 4.0
SCROLL_ITERATIONS = 5
SCROLL_PAUSE_SEC = 1.2
