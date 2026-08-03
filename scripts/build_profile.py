#!/usr/bin/env python3
"""
build_profile.py — build a CV_PROFILE.md from scraped jobs.
Usage:
    python3 build_profile.py --keywords "Jenkins AWS Python"
"""

import sys
import csv
import argparse
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import config


def parse_args():
    p = argparse.ArgumentParser(description="Build CV profile from job data")
    p.add_argument("--keywords", "-k", default="")
    p.add_argument("--input-csv", "-i", default=None)
    return p.parse_args()


def extract_skills_from_titles(jobs: list[dict]) -> Counter:
    """Count common keywords across job titles to infer hot skills."""
    common = {
        "python", "java", "aws", "azure", "gcp", "docker", "kubernetes", "k8s",
        "jenkins", "ci/cd", "cicd", "terraform", "ansible", "linux", "sql",
        "mongodb", "postgresql", "mysql", "redis", "kafka", "spark", "hadoop",
        "git", "github", "gitlab", "jira", "agile", "scrum", "devops", "sre",
        "cloud", "security", "networking", "bash", "powershell", "golang", "rust",
        "machine learning", "ml", "ai", "data engineer", "data analyst",
        "project manager", "pmp", "scrum master",
    }
    title_text = " ".join(j.get("title", "").lower() for j in jobs)
    found = Counter()
    for skill in common:
        if skill in title_text:
            found[skill] += 1
    return found


def build_profile(keywords: str, jobs: list[dict]) -> str:
    skills_counter = extract_skills_from_titles(jobs)
    top_skills = [s for s, _ in skills_counter.most_common(15)]

    # Parse years / level hints from titles
    level_titles = [j.get("title", "").lower() for j in jobs]
    is_senior = any(w in t for t in level_titles for w in ["senior", "lead", "principal", "architect", "manager", "head"])
    is_junior = any(w in t for t in level_titles for w in ["junior", "entry", "associate", "intern", "fresh"])

    level = "Senior / Lead" if is_senior and not is_junior else "Mid-Level"
    if is_junior and not is_senior:
        level = "Junior / Entry"

    lines = [
        "# CV Profile Summary",
        "",
        "## Professional Summary",
        "",
        f"Results-driven {level} professional with hands-on expertise in **{', '.join(top_skills[:8])}**. "
        f"Experienced in designing, implementing, and maintaining scalable infrastructure and data systems. "
        f"Strong background in CI/CD pipelines, cloud platforms, and automation. "
        f"Passionate about building reliable, high-performance systems and continuously improving engineering processes.",
        "",
        "## Core Competencies",
        "",
    ]

    # Group skills by category
    categories = {
        "Cloud & DevOps": ["aws", "azure", "gcp", "docker", "kubernetes", "jenkins", "ci/cd", "terraform", "ansible", "linux"],
        "Data": ["python", "sql", "postgresql", "mysql", "mongodb", "redis", "kafka", "spark", "hadoop"],
        "Languages": ["python", "golang", "rust", "bash", "powershell", "java"],
        "Practices": ["agile", "scrum", "git", "jira", "security", "networking"],
    }

    for cat, cat_skills in categories.items():
        matched = [s for s in cat_skills if s in top_skills]
        if matched:
            lines.append(f"**{cat}:** {', '.join(matched)}")

    lines += [
        "",
        "## Key Trends from Recent Applications",
        "",
        f"Based on {len(jobs)} recent job postings in the market:",
        "",
    ]

    if top_skills:
        lines.append(f"- Most in-demand skills: **{', '.join(top_skills[:8])}**")
    lines.append(f"- Detected level focus: **{level}** roles")
    lines.append("")

    lines += [
        "## Recommended CV Keywords",
        "",
        "Include these naturally in your CV to pass ATS screening:",
        "",
    ]
    for skill in top_skills:
        lines.append(f"- {skill.title()}")

    lines += [
        "",
        "## Job Search Focus",
        "",
        f"**Primary keywords used:** {keywords}",
        "",
        "_Profile generated automatically. Edit manually to add real achievements and numbers._",
    ]

    return "\n".join(lines)


def main():
    args = parse_args()
    keywords = args.keywords or config.DEFAULT_KEYWORDS

    jobs = []
    csv_path = Path(args.input_csv) if args.input_csv else config.OUTPUT_CSV

    if csv_path.exists():
        reader = csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines())
        jobs = list(reader)
        print(f"Loaded {len(jobs)} jobs from {csv_path}")
    else:
        print(f"[WARN] No CSV found at {csv_path}, building profile from keywords only")

    profile = build_profile(keywords, jobs)

    config.CV_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CV_PROFILE_PATH.write_text(profile, encoding="utf-8")
    print(f"\n✓ Profile saved → {config.CV_PROFILE_PATH}")
    print("\n--- PREVIEW ---")
    print(profile[:1000])


if __name__ == "__main__":
    main()
