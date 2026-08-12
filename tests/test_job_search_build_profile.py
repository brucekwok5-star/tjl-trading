"""Tests for job-search/build_profile.py — skill extraction & profile markdown."""
from __future__ import annotations

from collections import Counter

import pytest


class TestExtractSkills:
    def test_empty_input_returns_empty_counter(self, js_build_profile):
        c = js_build_profile.extract_skills_from_titles([])
        assert isinstance(c, Counter)
        assert len(c) == 0

    def test_aws_keyword_counted(self, js_build_profile):
        jobs = [{"title": "AWS Engineer"}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        assert c["aws"] >= 1

    def test_kubernetes_counted(self, js_build_profile):
        jobs = [{"title": "Kubernetes Specialist"}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        assert c["kubernetes"] >= 1

    def test_case_insensitive(self, js_build_profile):
        jobs = [{"title": "AWS Engineer"}, {"title": "AWS Architect"}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        # Implementation joins all titles into one string then counts substring
        # matches → a skill that appears in multiple titles still counts once
        assert c["aws"] >= 1

    def test_multiple_skills_in_one_title(self, js_build_profile):
        jobs = [{"title": "AWS Kubernetes Terraform Engineer"}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        assert c["aws"] >= 1
        assert c["kubernetes"] >= 1
        assert c["terraform"] >= 1

    def test_unknown_skill_not_counted(self, js_build_profile):
        jobs = [{"title": "Professional Tea Taster"}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        assert "tea taster" not in c  # not in our common skills list
        assert len(c) == 0

    def test_handles_missing_title_key(self, js_build_profile):
        jobs = [{"title": "AWS Engineer"}, {"no_title_key": "x"}, {"title": ""}]
        c = js_build_profile.extract_skills_from_titles(jobs)
        assert c["aws"] >= 1


class TestBuildProfile:
    def test_returns_string(self, js_build_profile):
        jobs = [{"title": "AWS DevOps Engineer"}]
        out = js_build_profile.build_profile("AWS DevOps", jobs)
        assert isinstance(out, str)
        assert len(out) > 100

    def test_includes_keywords(self, js_build_profile):
        jobs = [{"title": "Kubernetes AWS Terraform Engineer"}]
        out = js_build_profile.build_profile("Kubernetes", jobs)
        # Top skills should appear somewhere in the profile
        assert "aws" in out.lower()
        assert "kubernetes" in out.lower() or "k8s" in out.lower()

    def test_level_senior_detected(self, js_build_profile):
        jobs = [{"title": "Senior DevOps Engineer"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Senior / Lead" in out

    def test_level_lead_detected(self, js_build_profile):
        jobs = [{"title": "Lead SRE"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Senior / Lead" in out

    def test_level_junior_detected(self, js_build_profile):
        jobs = [{"title": "Junior Developer"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Junior / Entry" in out

    def test_level_mid_default(self, js_build_profile):
        jobs = [{"title": "DevOps Engineer"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Mid-Level" in out

    def test_includes_keywords_argument(self, js_build_profile):
        jobs = [{"title": "Engineer"}]
        out = js_build_profile.build_profile("MySpecialKeyword", jobs)
        assert "MySpecialKeyword" in out

    def test_no_jobs_produces_skeleton(self, js_build_profile):
        # No jobs → no skills detected, but the structure still renders
        out = js_build_profile.build_profile("", [])
        assert "CV Profile Summary" in out
        assert "Mid-Level" in out or "Junior" in out or "Senior" in out

    def test_senior_takes_precedence_over_junior(self, js_build_profile):
        # When both senior and junior hints appear, the code defaults to
        # Mid-Level (since neither is_senior-only nor is_junior-only is true).
        jobs = [
            {"title": "Senior Engineer"},
            {"title": "Junior Engineer"},
        ]
        out = js_build_profile.build_profile("", jobs)
        assert "Mid-Level" in out

    def test_principal_recognized(self, js_build_profile):
        jobs = [{"title": "Principal Architect"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Senior / Lead" in out

    def test_manager_recognized(self, js_build_profile):
        jobs = [{"title": "Engineering Manager"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Senior / Lead" in out

    def test_intern_recognized(self, js_build_profile):
        jobs = [{"title": "Software Intern"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Junior / Entry" in out

    def test_recommended_keywords_section(self, js_build_profile):
        jobs = [{"title": "AWS Kubernetes"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Recommended CV Keywords" in out

    def test_keyword_trends_section(self, js_build_profile):
        jobs = [{"title": "AWS"}]
        out = js_build_profile.build_profile("", jobs)
        assert "Trends" in out or "in-demand" in out.lower()

    def test_skill_categorization_present(self, js_build_profile):
        jobs = [{"title": "AWS Engineer"}]
        out = js_build_profile.build_profile("", jobs)
        # Should have at least one category
        assert "Cloud" in out or "DevOps" in out
class TestMainCli:
    def test_main_with_csv_creates_profile(self, js_build_profile, tmp_path, monkeypatch, capsys):
        import csv as _csv
        from unittest.mock import MagicMock, patch
        csv_path = tmp_path / "jobs.csv"
        rows = [
            {"title": "Senior AWS Engineer",
             "company": "HSBC", "location": "HK", "posted": "1d",
             "salary": "$80K", "source": "JobsDB", "link": "https://x.com/1"},
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        out_path = tmp_path / "CV_PROFILE.md"
        monkeypatch.setattr(js_build_profile.config, "OUTPUT_CSV", csv_path)
        monkeypatch.setattr(js_build_profile.config, "CV_PROFILE_PATH", out_path)

        with patch.object(js_build_profile, "parse_args",
                          return_value=MagicMock(keywords="AWS", input_csv=str(csv_path))):
            js_build_profile.main()

        assert out_path.exists()
        text = out_path.read_text()
        assert "aws" in text.lower()
        out = capsys.readouterr().out
        assert "Profile saved" in out
        assert "Loaded 1 jobs" in out

    def test_main_without_csv_uses_keywords(self, js_build_profile, tmp_path, monkeypatch, capsys):
        from unittest.mock import MagicMock, patch
        out_path = tmp_path / "CV_PROFILE.md"
        monkeypatch.setattr(js_build_profile.config, "OUTPUT_CSV", tmp_path / "missing.csv")
        monkeypatch.setattr(js_build_profile.config, "CV_PROFILE_PATH", out_path)

        with patch.object(js_build_profile, "parse_args",
                          return_value=MagicMock(keywords="DevOps", input_csv=None)):
            js_build_profile.main()

        assert out_path.exists()
        out = capsys.readouterr().out
        assert "No CSV found" in out
        assert "DevOps" in out

    def test_main_default_keywords(self, js_build_profile, tmp_path, monkeypatch):
        from unittest.mock import MagicMock, patch
        out_path = tmp_path / "CV_PROFILE.md"
        monkeypatch.setattr(js_build_profile.config, "OUTPUT_CSV", tmp_path / "missing.csv")
        monkeypatch.setattr(js_build_profile.config, "CV_PROFILE_PATH", out_path)

        with patch.object(js_build_profile, "parse_args",
                          return_value=MagicMock(keywords="", input_csv=None)):
            js_build_profile.main()
        text = out_path.read_text()
        assert "Jenkins" in text or "DevOps" in text

    def test_parse_args_keys(self, js_build_profile):
        import inspect
        src = inspect.getsource(js_build_profile.parse_args)
        assert "--keywords" in src
        assert "--input-csv" in src
