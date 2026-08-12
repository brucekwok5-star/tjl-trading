"""Tests for job-search/config.py — paths, constants, SITES schema."""
from __future__ import annotations

import pytest


class TestPaths:
    def test_workspace_dir_in_hermes(self, js_config):
        assert ".hermes" in str(js_config.WORKSPACE_DIR)
        assert "job-search" in str(js_config.WORKSPACE_DIR)

    def test_jd_dir_under_workspace(self, js_config):
        assert js_config.JD_DIR.parent == js_config.WORKSPACE_DIR

    def test_excel_path_under_workspace(self, js_config):
        assert js_config.EXCEL_PATH.parent == js_config.WORKSPACE_DIR

    def test_cv_profile_path_under_workspace(self, js_config):
        assert js_config.CV_PROFILE_PATH.parent == js_config.WORKSPACE_DIR

    def test_output_csv_in_tmp(self, js_config):
        assert str(js_config.OUTPUT_CSV).startswith("/tmp/")

    def test_cookie_file_in_tmp(self, js_config):
        assert str(js_config.COOKIE_FILE).startswith("/tmp/")

    def test_paths_are_pathlib(self, js_config):
        import pathlib
        for p in (js_config.WORKSPACE_DIR, js_config.JD_DIR, js_config.CV_DIR,
                 js_config.OUTPUT_CSV, js_config.COOKIE_FILE, js_config.EXCEL_PATH,
                 js_config.CV_PROFILE_PATH):
            assert isinstance(p, pathlib.Path)


class TestDefaults:
    def test_default_keywords_set(self, js_config):
        assert js_config.DEFAULT_KEYWORDS
        assert isinstance(js_config.DEFAULT_KEYWORDS, str)
        assert len(js_config.DEFAULT_KEYWORDS) > 0

    def test_search_days_positive(self, js_config):
        assert js_config.SEARCH_DAYS > 0
        assert js_config.SEARCH_DAYS <= 30  # reasonable

    def test_hk_only_true(self, js_config):
        assert js_config.HK_ONLY is True


class TestSites:
    def test_three_sites(self, js_config):
        assert len(js_config.SITES) == 3

    def test_required_site_names(self, js_config):
        names = {s["name"] for s in js_config.SITES}
        for must in ("JobsDB", "eFinancialCareers", "Indeed"):
            assert must in names, f"{must} missing from SITES"

    def test_all_sites_hk(self, js_config):
        for site in js_config.SITES:
            url = site["url"].lower()
            assert "hong" in url or "hk" in url, \
                f"{site['name']} URL not HK-restricted: {site['url']}"

    def test_all_sites_have_required_fields(self, js_config):
        required = ["name", "url", "title_sel", "company_sel", "location_sel",
                    "posted_sel", "salary_sel", "link_sel", "link_prefix",
                    "job_card_sel"]
        for site in js_config.SITES:
            for k in required:
                assert k in site, f"{site.get('name','?')} missing {k}"

    def test_link_sel_is_string_or_list(self, js_config):
        for site in js_config.SITES:
            assert isinstance(site["link_sel"], (str, list))

    def test_link_prefix_https(self, js_config):
        for site in js_config.SITES:
            assert site["link_prefix"].startswith("https://")

    def test_url_template_has_keywords_days(self, js_config):
        # Most sites use both {keywords} and {days}; eFinancial uses {keywords}
        # only with filters.postedDate=THREE.
        for site in js_config.SITES:
            url = site["url"]
            assert "{keywords}" in url, f"{site['name']} URL missing {{keywords}}"
            if site["name"] != "eFinancialCareers":
                assert "{days}" in url, f"{site['name']} URL missing {{days}}"


class TestAntiBot:
    def test_retry_settings(self, js_config):
        assert js_config.RETRY_COUNT >= 1
        assert js_config.RETRY_DELAY_SEC > 0

    def test_human_delay_range(self, js_config):
        assert js_config.HUMAN_DELAY_MIN > 0
        assert js_config.HUMAN_DELAY_MAX > js_config.HUMAN_DELAY_MIN
        assert js_config.HUMAN_DELAY_MAX <= 30  # reasonable upper bound

    def test_scroll_settings(self, js_config):
        assert js_config.SCROLL_ITERATIONS >= 1
        assert js_config.SCROLL_PAUSE_SEC > 0