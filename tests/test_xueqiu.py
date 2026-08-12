"""Tests for xueqiu_expand_search.py — Xueqiu user expansion via Playwright."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ── Load the script (it has top-level side effects, so we stub deps first) ────
@pytest.fixture(scope="session")
def xueqiu_mod():
    """Import xueqiu_expand_search.py with playwright + openclaw stubbed."""
    # Stub playwright
    playwright_mod = MagicMock()
    sys.modules["playwright"] = playwright_mod
    sys.modules["playwright.sync_api"] = playwright_mod.sync_api
    sys.modules["playwright.sync_api"].sync_playwright = MagicMock()

    script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "xueqiu_expand_search.py",
    )
    spec = importlib.util.spec_from_file_location("xueqiu_expand_search", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGetCookies:
    def test_returns_only_xueqiu_cookies_with_value(self, xueqiu_mod):
        fake_stdout = json.dumps([
            {"domain": "xueqiu.com", "value": "abc123", "name": "xq_a_token"},
            {"domain": "xueqiu.com", "value": "", "name": "empty"},
            {"domain": "other.com", "value": "should_skip", "name": "other"},
            {"domain": ".xueqiu.com", "value": "tok2", "name": "xqat"},
        ])
        fake_proc = MagicMock(stdout=fake_stdout)
        with patch.object(xueqiu_mod.subprocess, "run", return_value=fake_proc):
            cookies = xueqiu_mod.get_cookies()
        # Only xueqiu cookies with non-empty value
        assert len(cookies) == 2
        assert all("xueqiu" in c["domain"] for c in cookies)
        assert all(c["value"] for c in cookies)

    def test_returns_empty_when_no_cookies(self, xueqiu_mod):
        fake_proc = MagicMock(stdout="[]")
        with patch.object(xueqiu_mod.subprocess, "run", return_value=fake_proc):
            cookies = xueqiu_mod.get_cookies()
        assert cookies == []


class TestIdExtractionRegex:
    """Test the regex used to extract user IDs from Xueqiu HTML."""

    def test_extracts_from_href_class_order(self):
        # Simulate the regex used in the script
        html = '<a href="/1234567" class="user-name">Bob</a>'
        ids = re.findall(r'href="/(\d{7,10})"[^>]*class="[^"]*user-name[^"]*"', html)
        assert ids == ["1234567"]

    def test_extracts_from_class_href_order(self):
        html = '<a class="user-name" href="/9876543">Alice</a>'
        ids = re.findall(r'class="user-name[^"]*"[^>]*href="/(\d{7,10})"', html)
        assert ids == ["9876543"]

    def test_ignores_short_ids(self):
        html = '<a href="/1234" class="user-name">X</a>'  # too short
        ids = re.findall(r'href="/(\d{7,10})"', html)
        assert ids == []  # regex requires 7-10 digits

    def test_ignores_ids_below_threshold(self):
        # The script filters int(x) > 1e6
        html = '<a href="/999999" class="user-name">X</a>'  # 6 digits = 999999, but not 7+ digit
        ids = re.findall(r'href="/(\d{7,10})"[^>]*class="[^"]*user-name[^"]*"', html)
        assert ids == []  # filtered by digit count

    def test_multiple_users(self):
        html = '''
        <a href="/1234567" class="user-name">A</a>
        <a href="/2345678" class="user-name">B</a>
        <a href="/3456789" class="user-name">C</a>
        '''
        ids = re.findall(r'href="/(\d{7,10})"[^>]*class="[^"]*user-name[^"]*"', html)
        ids += re.findall(r'class="user-name[^"]*"[^>]*href="/(\d{7,10})"', html)
        ids = list(set([int(x) for x in ids if int(x) > 1e6]))
        assert set(ids) == {1234567, 2345678, 3456789}


class TestScriptConstants:
    """Verify the script has the expected search terms & data layout."""

    def test_search_terms_present(self, xueqiu_mod):
        # The script defines `terms` as a list of search keywords
        # Re-run the file's body to read `terms` — but easier to check via __dict__
        # The script's main() isn't a function, so we rely on direct import
        # exposing the module-level constants.
        # Inspect the source for the expected terms
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "xueqiu_expand_search.py")) as f:
            src = f.read()
        assert "港股投資達人" in src
        assert "基金經理" in src
        assert "分析師" in src

    def test_output_path_is_temp(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "xueqiu_expand_search.py")) as f:
            src = f.read()
        assert "/tmp/xueqiu_expanded_users.json" in src


class TestIntegrationWithMockBrowser:
    """End-to-end test using a mocked Playwright browser."""

    def test_full_flow_with_mocks(self, xueqiu_mod, tmp_path, monkeypatch):
        # Output path to redirect to
        output_file = tmp_path / "users.json"

        # HTML per search term
        fake_html_per_term = {
            "港股投資達人": '<a href="/1234567" class="user-name">A</a>',
            "炒股致富":     '<a href="/2345678" class="user-name">B</a>',
            "基金經理":     '<a href="/3456789" class="user-name">C</a>',
            "分析師":       "",  # no users
            "李大霄":       '<a href="/4567890" class="user-name">D</a>',
        }

        fake_page = MagicMock()
        def fake_goto(url, **kw):
            for term, html in fake_html_per_term.items():
                if term.replace(' ', '%20') in url:
                    fake_page.content.return_value = html
                    return
            fake_page.content.return_value = ""
        fake_page.goto.side_effect = fake_goto

        fake_ctx = MagicMock()
        fake_ctx.new_page.return_value = fake_page

        fake_browser = MagicMock()
        fake_browser.new_context.return_value = fake_ctx

        fake_p = MagicMock()
        fake_p.chromium.launch.return_value = fake_browser
        xueqiu_mod.sync_playwright.return_value.__enter__.return_value = fake_p

        # Build a fake open() that redirects both output paths to tmp_path
        real_open = open

        def fake_open(p, *a, **kw):
            if p in ("/tmp/xueqiu_user_ids.txt", "/tmp/xueqiu_expanded_users.json"):
                return real_open(str(output_file), *a, **kw)
            return real_open(p, *a, **kw)

        with patch("builtins.open", side_effect=fake_open):
            with patch.object(xueqiu_mod.subprocess, "run",
                              return_value=MagicMock(stdout=json.dumps([
                                  {"domain": "xueqiu.com", "value": "tok"}
                              ]))):
                # Stub out sleeps so the test doesn't wait 5*3.5s per term.
                with patch.object(xueqiu_mod.time, "sleep", return_value=None):
                    # Call the extracted function directly (post-refactor, the
                    # module no longer runs side effects on import).
                    xueqiu_mod.run_search(output_path=str(output_file))

        # Verify the fake browser was launched and 5 terms visited
        assert fake_p.chromium.launch.called
        assert fake_page.goto.call_count == 5

    def test_handles_goto_exception(self, xueqiu_mod, monkeypatch):
        # Ensure goto exception is caught (script continues to next term)
        fake_page = MagicMock()
        fake_page.goto.side_effect = RuntimeError("network error")
        fake_page.content.return_value = ""

        fake_ctx = MagicMock()
        fake_ctx.new_page.return_value = fake_page
        fake_browser = MagicMock()
        fake_browser.new_context.return_value = fake_ctx
        fake_p = MagicMock()
        fake_p.chromium.launch.return_value = fake_browser
        xueqiu_mod.sync_playwright.return_value.__enter__.return_value = fake_p

        with patch.object(xueqiu_mod.subprocess, "run",
                          return_value=MagicMock(stdout="[]")):
            # Stub sleeps so the test doesn't wait.
            with patch.object(xueqiu_mod.time, "sleep", return_value=None):
                # Call the extracted function directly.
                xueqiu_mod.run_search()

        assert fake_page.goto.call_count == 5  # all terms attempted
        assert fake_p.chromium.launch.called


class _DummyFile:
    """Stand-in for the redirected open() above."""
    def __init__(self):
        self._buf = []
    def write(self, s): self._buf.append(s)
    def __enter__(self): return self
    def __exit__(self, *a): pass