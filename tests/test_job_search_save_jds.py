"""Tests for job-search/save_jds.py — JD fetching, HTML stripping, folder creation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── fetch_jd_text: web_extract + curl fallback ───────────────────────────────

class TestFetchJdText:
    def test_returns_empty_for_non_url(self, js_save_jds):
        assert js_save_jds.fetch_jd_text("") == ""
        assert js_save_jds.fetch_jd_text("not-a-url") == ""

    def test_uses_web_extract_when_available(self, js_save_jds):
        # Provide a hermes_tools.web_extract stub via sys.modules
        import sys
        hermes_pkg = MagicMock()
        web_extract_mod = MagicMock()
        web_extract_mod.return_value = {
            "results": [{"content": "Hello world job description text " * 20}]
        }
        hermes_pkg.web_extract = web_extract_mod
        sys.modules["hermes_tools"] = hermes_pkg
        try:
            with patch("subprocess.run") as mock_run:
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert out  # non-empty
            assert "Hello world" in out
            # curl should NOT have been called
            assert not mock_run.called
        finally:
            del sys.modules["hermes_tools"]

    def test_falls_back_to_curl(self, js_save_jds):
        # Force hermes_tools.web_extract to raise (simulating "not in Hermes
        # context" — the real hermes_tools is importable here so we can't just
        # pop it from sys.modules).
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    stdout="<html>" + ("Real job description content here " * 20) + "</html>")
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert mock_run.called
            assert "Real job description" in out
        finally:
            del sys.modules["hermes_tools"]

    def test_strips_html_tags(self, js_save_jds):
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            html = (
                "<html><head><style>body{}</style></head>"
                "<body><h1>Title</h1><p>" + ("This is the job description text we want to keep after stripping all HTML tags. " * 5) + "</p>"
                "<script>alert('x')</script></body></html>"
            )
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=html)
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert "Title" in out
            assert "This is the job description text we want to keep after stripping all HTML tags." in out
            assert "<" not in out and ">" not in out
            assert "alert" not in out
        finally:
            del sys.modules["hermes_tools"]

    def test_decodes_html_entities(self, js_save_jds):
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            html = "<html><body>Tom &amp; Jerry &nbsp; are &lt;cool&gt; &quot;friends&quot;. " + ("This is a longer job description that passes the length threshold so it isn't rejected as too short. " * 5) + "</body></html>"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=html)
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert "Tom & Jerry" in out
            assert "<cool>" in out
            assert '"friends"' in out
        finally:
            del sys.modules["hermes_tools"]

    def test_returns_empty_on_curl_exception(self, js_save_jds):
        import sys
        sys.modules.pop("hermes_tools", None)
        with patch("subprocess.run",
                          side_effect=FileNotFoundError("curl not found")):
            out = js_save_jds.fetch_jd_text("https://example.com/job/1")
        assert out == ""

    def test_returns_empty_on_js_challenge(self, js_save_jds):
        # Page that looks like a Cloudflare JS challenge
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            js_challenge = (
                "<html><body>Security check: please verify you are a human. "
                "Enable JavaScript and reload. "
                "Checking your browser before accessing the site.</body></html>"
            )
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=js_challenge)
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert out == ""
        finally:
            del sys.modules["hermes_tools"]

    def test_returns_empty_when_response_too_short(self, js_save_jds):
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="<html>x</html>")  # < 300 chars
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert out == ""
        finally:
            del sys.modules["hermes_tools"]

    def test_truncates_very_long_text(self, js_save_jds):
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            long_text = "x" * 100_000
            html = f"<html><body>{long_text}</body></html>"
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout=html)
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            # Truncated at 50_000 + suffix
            assert "truncated" in out.lower() or len(out) <= 51_000
        finally:
            del sys.modules["hermes_tools"]

    def test_curl_user_agent_set(self, js_save_jds):
        import sys
        raising_pkg = MagicMock()
        raising_pkg.web_extract.side_effect = ImportError("no web_extract")
        # Also delete the cached submodule reference so `from hermes_tools
        # import web_extract` re-fetches and calls our mock (which then raises).
        sys.modules.pop("hermes_tools.web_extract", None)
        sys.modules["hermes_tools"] = raising_pkg
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(stdout="<html>job content here</html>")
                js_save_jds.fetch_jd_text("https://example.com/job/1")
            cmd = mock_run.call_args[0][0]
            assert "curl" in cmd[0]
            # User agent should be a modern browser string
            ua = next((a for a in cmd if isinstance(a, str) and "Mozilla" in a), None)
            assert ua is not None
            assert "Chrome" in ua or "Safari" in ua
        finally:
            del sys.modules["hermes_tools"]

    def test_web_extract_skips_empty_content(self, js_save_jds):
        import sys
        hermes_pkg = MagicMock()
        web_extract_mod = MagicMock()
        web_extract_mod.return_value = {
            "results": [
                {"content": ""},       # empty → skip
                {"content": None},     # None → skip
                {"content": "valid content here for testing the job description in detail"},
            ]
        }
        hermes_pkg.web_extract = web_extract_mod
        sys.modules["hermes_tools"] = hermes_pkg
        try:
            with patch("subprocess.run") as mock_run:
                out = js_save_jds.fetch_jd_text("https://example.com/job/1")
            assert "valid content" in out
        finally:
            del sys.modules["hermes_tools"]


# ── Helpers: job_id, safe_name ────────────────────────────────────────────────

class TestJobId:
    def test_same_link_same_hash(self, js_save_jds):
        a = js_save_jds.job_id("https://hk.jobsdb.com/job/123")
        b = js_save_jds.job_id("https://hk.jobsdb.com/job/123")
        assert a == b

    def test_different_links_different_hashes(self, js_save_jds):
        a = js_save_jds.job_id("https://hk.jobsdb.com/job/123")
        b = js_save_jds.job_id("https://hk.jobsdb.com/job/456")
        assert a != b

    def test_empty_link_returns_noid(self, js_save_jds):
        assert js_save_jds.job_id("") == "noid"

    def test_hash_is_8_chars(self, js_save_jds):
        h = js_save_jds.job_id("https://example.com/abc")
        assert len(h) == 8


class TestSafeName:
    def test_alphanumeric_kept(self, js_save_jds):
        assert js_save_jds.safe_name("HSBC123") == "HSBC123"

    def test_spaces_kept(self, js_save_jds):
        assert js_save_jds.safe_name("Foo Bar") == "Foo Bar"

    def test_special_chars_replaced(self, js_save_jds):
        result = js_save_jds.safe_name("Foo/Bar:Baz")
        # Forward slash and colon are NOT in allowed set → replaced with _
        assert "/" not in result
        assert ":" not in result

    def test_dashes_and_underscores_kept(self, js_save_jds):
        assert js_save_jds.safe_name("foo-bar_baz") == "foo-bar_baz"

    def test_max_length_truncates(self, js_save_jds):
        long = "A" * 100
        result = js_save_jds.safe_name(long, max_len=20)
        assert len(result) == 20

    def test_strips_whitespace(self, js_save_jds):
        assert js_save_jds.safe_name("  hello  ") == "hello"


# ── save_jds: end-to-end folder creation ──────────────────────────────────────

class TestSaveJds:
    def test_no_csv_returns_gracefully(self, js_save_jds, tmp_path, capsys):
        js_save_jds.save_jds(tmp_path / "missing.csv")
        out = capsys.readouterr().out
        assert "ERROR" in out

    def test_creates_job_folder(self, js_save_jds, tmp_job_csv, tmp_path):
        # Redirect JD_DIR to tmp_path
        from unittest.mock import patch
        original_jd_dir = js_save_jds.config.JD_DIR
        # Mock fetch_jd_text so save_jds doesn't hit the network / web_extract.
        with patch.object(js_save_jds.config, "JD_DIR", tmp_path / "JDs"):
            with patch.object(js_save_jds.time, "sleep"):  # skip rate-limit
                with patch.object(js_save_jds, "fetch_jd_text",
                                  return_value=("Real job description content here " * 20)):
                    js_save_jds.save_jds(tmp_job_csv)
            # Check folders were created
            sources = list((tmp_path / "JDs").iterdir())
            assert any(s.name == "JobsDB" for s in sources)
            assert any(s.name == "eFinancialCareers" for s in sources)
            # Find a specific job folder
            jobsdb = (tmp_path / "JDs") / "JobsDB"
            job_folders = list(jobsdb.iterdir())
            assert len(job_folders) == 2  # 2 JobsDB jobs in fixture
            # Each has a job.txt
            for jf in job_folders:
                assert (jf / "job.txt").exists()
        _ = original_jd_dir  # silence flake8 unused

    def test_job_txt_has_required_sections(self, js_save_jds, tmp_job_csv, tmp_path):
        from unittest.mock import patch
        with patch.object(js_save_jds.config, "JD_DIR", tmp_path / "JDs"):
            with patch.object(js_save_jds.time, "sleep"):
                with patch.object(js_save_jds, "fetch_jd_text",
                                  return_value=("Real job description content here " * 20)):
                    js_save_jds.save_jds(tmp_job_csv)
        # Find first job.txt
        for folder in (tmp_path / "JDs").rglob("job.txt"):
            text = folder.read_text(encoding="utf-8")
            for field in ("Source:", "Company:", "Title:", "Location:",
                          "Salary:", "Link:"):
                assert field in text, f"job.txt missing {field}"
            assert "## Full Job Description" in text
            break

    def test_handles_csv_with_unicode_decode_error(self, js_save_jds, tmp_path):
        # Write a CSV with Latin-1 encoding (simulates non-UTF8 input)
        csv_path = tmp_path / "latin.csv"
        csv_path.write_bytes(b"title,company\n\xe9,caf\xe9\n")
        # Should not raise — falls back to latin-1
        from unittest.mock import patch
        with patch.object(js_save_jds.config, "JD_DIR", tmp_path / "JDs"):
            with patch.object(js_save_jds.time, "sleep"):
                js_save_jds.save_jds(csv_path)
        # Folder created with safe_name applied
        assert (tmp_path / "JDs").exists()

    def test_handles_missing_link_field(self, js_save_jds, tmp_path):
        # CSV with missing 'link' key — job_id should return "noid"
        csv_path = tmp_path / "no_link.csv"
        csv_path.write_text("title,company\nEngineer,Acme\n", encoding="utf-8")
        from unittest.mock import patch
        with patch.object(js_save_jds.config, "JD_DIR", tmp_path / "JDs"):
            with patch.object(js_save_jds.time, "sleep"):
                js_save_jds.save_jds(csv_path)
        # job.txt should exist with empty Link
        for job_txt in (tmp_path / "JDs").rglob("job.txt"):
            assert "Link:" in job_txt.read_text(encoding="utf-8")
            break

    def test_sanitizes_invalid_filename_chars(self, js_save_jds, tmp_job_csv, tmp_path):
        # Modify CSV to have a company name with invalid filename chars
        import csv as _csv
        csv_path = tmp_path / "tricky.csv"
        rows = [
            {"title": "Engineer", "company": "Foo/Bar:Baz",
             "location": "HK", "posted": "1d", "salary": "$50K",
             "source": "JobsDB", "link": "https://x.com/1"},
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        from unittest.mock import patch
        with patch.object(js_save_jds.config, "JD_DIR", tmp_path / "JDs"):
            with patch.object(js_save_jds.time, "sleep"):
                with patch.object(js_save_jds, "fetch_jd_text",
                                  return_value=("Real job description content here " * 20)):
                    js_save_jds.save_jds(csv_path)
        # Folder name should not contain invalid chars
        for folder in (tmp_path / "JDs").rglob("*"):
            if folder.is_dir():
                assert "/" not in folder.name
                assert ":" not in folder.name