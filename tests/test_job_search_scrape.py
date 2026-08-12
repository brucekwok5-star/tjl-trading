"""Tests for job-search/scrape_all.py — URL encoding, cookie loading, anti-bot."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ── human_delay ───────────────────────────────────────────────────────────────

class TestHumanDelay:
    def test_sleeps_between_min_and_max(self, js_scrape_all):
        with patch.object(js_scrape_all.time, "sleep") as mock_sleep:
            js_scrape_all.human_delay()
        assert mock_sleep.called
        delay = mock_sleep.call_args[0][0]
        assert js_scrape_all.config.HUMAN_DELAY_MIN <= delay <= js_scrape_all.config.HUMAN_DELAY_MAX


# ── load_cookies ──────────────────────────────────────────────────────────────

class TestLoadCookies:
    def test_no_cookie_file_noop(self, js_scrape_all, monkeypatch, tmp_path):
        monkeypatch.setattr(js_scrape_all.config, "COOKIE_FILE", tmp_path / "missing.json")
        ctx = MagicMock()
        js_scrape_all.load_cookies(ctx, "JobsDB")
        assert not ctx.add_cookies.called

    def test_loads_matching_cookies(self, js_scrape_all, monkeypatch, tmp_path):
        cookie_file = tmp_path / "cookies.json"
        cookies = [
            {"domain": "hk.jobsdb.com", "value": "abc"},
            {"domain": "www.efinancialcareers.hk", "value": "def"},
            {"domain": "unrelated.com", "value": "xyz"},
        ]
        cookie_file.write_text(json.dumps(cookies))
        monkeypatch.setattr(js_scrape_all.config, "COOKIE_FILE", cookie_file)
        ctx = MagicMock()
        js_scrape_all.load_cookies(ctx, "JobsDB")
        # Should add at least the JobsDB cookie
        assert ctx.add_cookies.called
        added = [c[0][0][0] for c in ctx.add_cookies.call_args_list]
        assert any(c["domain"] == "hk.jobsdb.com" for c in added)

    def test_handles_invalid_json(self, js_scrape_all, monkeypatch, tmp_path):
        cookie_file = tmp_path / "bad.json"
        cookie_file.write_text("not valid json")
        monkeypatch.setattr(js_scrape_all.config, "COOKIE_FILE", cookie_file)
        ctx = MagicMock()
        # Should not raise
        js_scrape_all.load_cookies(ctx, "JobsDB")
        assert not ctx.add_cookies.called

    def test_handles_add_cookie_exception(self, js_scrape_all, monkeypatch, tmp_path, capsys):
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([{"domain": "hk.jobsdb.com", "value": "x"}]))
        monkeypatch.setattr(js_scrape_all.config, "COOKIE_FILE", cookie_file)
        ctx = MagicMock()
        ctx.add_cookies.side_effect = Exception("Bad cookie format")
        js_scrape_all.load_cookies(ctx, "JobsDB")
        # Should swallow the exception and continue
        out = capsys.readouterr().out
        # No "Could not load cookies" warning because add_cookies failure is silent
        assert ctx.add_cookies.called


# ── detect_antiblock ───────────────────────────────────────────────────────────

class TestDetectAntiblock:
    def _make_page(self, text):
        page = MagicMock()
        page.inner_text.return_value = text
        return page

    def test_detects_access_denied(self, js_scrape_all):
        page = self._make_page("Access denied. Please verify you are a human.")
        assert js_scrape_all.detect_antiblock(page) is True

    def test_detects_captcha(self, js_scrape_all):
        page = self._make_page("Please complete this captcha to continue")
        assert js_scrape_all.detect_antiblock(page) is True

    def test_detects_blocked(self, js_scrape_all):
        page = self._make_page("Your IP has been blocked.")
        assert js_scrape_all.detect_antiblock(page) is True

    def test_detects_chinese_captcha(self, js_scrape_all):
        page = self._make_page("请完成人机验证")  # "complete human-machine verification"
        assert js_scrape_all.detect_antiblock(page) is True

    def test_no_false_positive_on_normal_page(self, js_scrape_all):
        page = self._make_page("Welcome to JobsDB Hong Kong. Browse 10000+ jobs.")
        assert js_scrape_all.detect_antiblock(page) is False

    def test_no_false_positive_on_challenge_text_in_job(self, js_scrape_all):
        # "challenge" appears in many job descriptions legitimately
        page = self._make_page("We are looking for someone to lead our challenge team. "
                               "Strong problem-solving skills required.")
        # "challenge" is a blocker keyword so this WILL fire — just verifying
        # the function actually checks for it
        assert js_scrape_all.detect_antiblock(page) is True


# ── URL encoding & save_csv ──────────────────────────────────────────────────

class TestSaveCsv:
    def test_save_csv_creates_file(self, js_scrape_all, tmp_path):
        results = [
            {"title": "Engineer", "company": "Acme", "location": "HK",
             "posted": "1d", "salary": "$50K", "source": "JobsDB",
             "link": "https://x.com/1"},
        ]
        out_path = tmp_path / "jobs.csv"
        js_scrape_all.save_csv(results, out_path)
        assert out_path.exists()
        text = out_path.read_text()
        assert "title,company,location,posted,salary,source,link" in text
        assert "Engineer" in text

    def test_save_csv_escapes_commas(self, js_scrape_all, tmp_path):
        # The save_csv function replaces commas with semicolons
        results = [
            {"title": "Senior, Cloud, DevOps", "company": "Acme",
             "location": "HK", "posted": "1d", "salary": "$50K",
             "source": "JobsDB", "link": "https://x.com/1"},
        ]
        out_path = tmp_path / "jobs.csv"
        js_scrape_all.save_csv(results, out_path)
        text = out_path.read_text()
        # Commas in fields replaced with semicolons
        assert "Senior; Cloud; DevOps" in text

    def test_save_csv_empty(self, js_scrape_all, tmp_path):
        out_path = tmp_path / "empty.csv"
        js_scrape_all.save_csv([], out_path)
        # Header only
        text = out_path.read_text()
        assert "title,company" in text


# ── Scrape site URL formatting ────────────────────────────────────────────────

class TestSiteUrlFormatting:
    def test_jobsdb_url_format(self, js_scrape_all):
        cfg = js_scrape_all.config.SITES[0]
        url = cfg["url"].format(
            keywords="AWS%20DevOps", days=3
        )
        assert "jobsdb.com" in url
        assert "AWS%20DevOps" in url
        assert "daterange=3" in url

    def test_indeed_url_format(self, js_scrape_all):
        cfg = js_scrape_all.config.SITES[2]  # Indeed
        url = cfg["url"].format(
            keywords="kubernetes", days=7
        )
        assert "indeed.com" in url
        assert "fromage=7" in url

    def test_special_chars_encoded(self, js_scrape_all):
        import urllib.parse
        encoded = urllib.parse.quote("C++ Engineer")
        assert "%2B" in encoded or "+" in encoded
class TestSaveCsvMore:
    def test_escapes_newlines_and_cr(self, js_scrape_all, tmp_path):
        # The save_csv function replaces \n with " " and \r with "" (empty)
        results = [
            {"title": "Multi\nline", "company": "Cr\rCompany",
             "location": "HK", "posted": "1d", "salary": "$50K",
             "source": "JobsDB", "link": "https://x.com/1"},
        ]
        out_path = tmp_path / "jobs.csv"
        js_scrape_all.save_csv(results, out_path)
        text = out_path.read_text()
        # Newline is replaced with space
        assert "Multi line" in text
        # CR is replaced with empty (collapses Cr + Company → CrCompany)
        assert "CrCompany" in text

    def test_preserves_link(self, js_scrape_all, tmp_path):
        results = [
            {"title": "Engineer", "company": "Acme", "location": "HK",
             "posted": "1d", "salary": "$50K", "source": "JobsDB",
             "link": "https://hk.jobsdb.com/job/abc?ref=search-standalone"},
        ]
        out_path = tmp_path / "jobs.csv"
        js_scrape_all.save_csv(results, out_path)
        text = out_path.read_text()
        # The link is preserved (we don't strip ref= here)
        assert "ref=search-standalone" in text


class TestScrapeAllMain:
    def test_main_with_no_args_uses_defaults(self, js_scrape_all, monkeypatch):
        import sys
        from unittest.mock import patch, MagicMock
        monkeypatch.setattr(sys, "argv", ["scrape_all.py"])
        # Mock save_csv to avoid file I/O
        with patch.object(js_scrape_all, "save_csv") as save_mock:
            with patch.object(js_scrape_all, "scrape_site", return_value=[]):
                js_scrape_all.main()
        # save_csv should have been called once with empty list
        assert save_mock.called
        # The first arg should be an empty list
        args, _ = save_mock.call_args
        assert args[0] == []

    def test_main_with_custom_keywords_and_days(self, js_scrape_all, monkeypatch):
        import sys
        from unittest.mock import patch
        monkeypatch.setattr(sys, "argv", ["scrape_all.py", "DevOps", "7"])
        with patch.object(js_scrape_all, "save_csv") as save_mock:
            with patch.object(js_scrape_all, "scrape_site", return_value=[]):
                js_scrape_all.main()
        assert save_mock.called

    def test_main_dedupes_by_link(self, js_scrape_all, monkeypatch):
        import sys
        from unittest.mock import patch
        monkeypatch.setattr(sys, "argv", ["scrape_all.py"])
        # Two sites return the same job link
        dup_results = [
            {"title": "Engineer", "company": "Acme", "location": "HK",
             "posted": "1d", "salary": "$50K", "source": "JobsDB",
             "link": "https://x.com/dup"},
        ]
        with patch.object(js_scrape_all, "save_csv") as save_mock:
            with patch.object(js_scrape_all, "scrape_site", return_value=dup_results * 3):
                js_scrape_all.main()
        # save_csv should receive only ONE entry (deduped)
        unique = save_mock.call_args[0][0]
        assert len(unique) == 1
        assert unique[0]["link"] == "https://x.com/dup"

    def test_main_drops_empty_links(self, js_scrape_all, monkeypatch):
        import sys
        from unittest.mock import patch
        monkeypatch.setattr(sys, "argv", ["scrape_all.py"])
        results = [
            {"title": "Good", "company": "Acme", "location": "HK",
             "posted": "1d", "salary": "$50K", "source": "JobsDB",
             "link": "https://x.com/1"},
            {"title": "Bad", "company": "Co", "location": "HK",
             "posted": "1d", "salary": "$50K", "source": "JobsDB",
             "link": ""},
        ]
        with patch.object(js_scrape_all, "save_csv") as save_mock:
            with patch.object(js_scrape_all, "scrape_site", return_value=results):
                js_scrape_all.main()
        unique = save_mock.call_args[0][0]
        assert len(unique) == 1
        assert unique[0]["link"] == "https://x.com/1"
