#!/usr/bin/env python3
"""
save_jds.py — read scraped CSV and save each job as a folder.
Folder structure: JDs/{Source}/{Company}_{Title}_{hash}/
  ├── job.txt           ← job details + link
  ├── cv.pdf            ← (you add your tailored CV here)
  └── cover_letter.docx ← (you add your cover letter here)

Usage:
    python3 save_jds.py [--input-csv /tmp/jobs_combined.csv]
"""

import csv
import hashlib
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import config


def job_id(link: str) -> str:
    """Short hash of link for a stable filename."""
    return hashlib.md5(link.encode()).hexdigest()[:8] if link else f"noid"


def safe_name(name: str, max_len: int = 40) -> str:
    """Make a name safe for a filesystem path."""
    cleaned = "".join(c if c.isalnum() or c in " -_" else "_" for c in name)
    return cleaned.strip()[:max_len]


def save_jds(csv_path: Path):
    if not csv_path.exists():
        print(f"[ERROR] CSV not found: {csv_path}")
        return

    try:
        text = csv_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = csv_path.read_text(encoding="latin-1")

    jobs = list(csv.DictReader(text.splitlines()))
    print(f"Loaded {len(jobs)} jobs from {csv_path}")

    saved = 0
    for job in jobs:
        source  = job.get("source", "Unknown").strip()
        title   = job.get("title", "untitled").strip()
        company = job.get("company", "unknown").strip()
        link    = job.get("link", "").strip()

        safe_company = safe_name(company, 30) or "UnknownCompany"
        safe_title   = safe_name(title, 40) or "untitled"
        jid          = job_id(link)

        # One folder per job
        folder_name = f"{safe_company}_{safe_title}_{jid}"
        folder_name = "".join(c if c not in "<>:\"|?*" else "_" for c in folder_name)
        job_dir = config.JD_DIR / source / folder_name
        job_dir.mkdir(parents=True, exist_ok=True)

        # job.txt — write job details
        job_lines = [
            f"Source:   {source}",
            f"Company:  {company}",
            f"Title:    {title}",
            f"Location: {job.get('location', 'N/A')}",
            f"Salary:   {job.get('salary', 'N/A')}",
            f"Posted:   {job.get('posted', 'N/A')}",
            f"Link:     {link}",
            "",
            "=" * 60,
            "",
            f"# {title} @ {company}",
            f"[View job posting]({link})",
            "",
            "## Notes",
            "(Add your notes after reviewing the JD)",
            "",
            "## Your Application Documents",
            "- cv.pdf           ← add your tailored CV",
            "- cover_letter.docx ← add your cover letter",
        ]
        (job_dir / "job.txt").write_text("\n".join(job_lines), encoding="utf-8")

        # Create placeholder stubs so user knows what goes where
        placeholder_note = (
            f"# {title} @ {company}\n\n"
            "Save your tailored CV as cv.pdf and cover letter as cover_letter.docx in this folder.\n"
            f"Job link: {link}\n"
        )
        if not (job_dir / "cv.pdf").exists():
            (job_dir / "cv.pdf").write_text("(placeholder — replace with your CV)", encoding="utf-8")
        if not (job_dir / "cover_letter.docx").exists():
            (job_dir / "cover_letter.docx").write_text("(placeholder — replace with your cover letter)", encoding="utf-8")

        saved += 1
        print(f"  [SAVE] {source}/{folder_name}/")

    print(f"\n✓ Saved {saved} job folders → {config.JD_DIR}")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Save jobs as individual folders with JD + CV slots")
    p.add_argument("--input-csv", "-i", default=None)
    args = p.parse_args()

    csv_path = Path(args.input_csv) if args.input_csv else config.OUTPUT_CSV
    save_jds(csv_path)


if __name__ == "__main__":
    main()
