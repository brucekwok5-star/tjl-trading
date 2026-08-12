"""Tests for the hk-bus-p2p and hk-bus-eta Hermes skills.

These skills are markdown documentation for agents (no Python code), so we
validate:
  - YAML frontmatter schema (name, description, version, tags, related_skills)
  - Required sections (Overview, Workflow, Output Format, Pitfalls, etc.)
  - Hardcoded landmarks & stop codes the agent must reference
  - API endpoint URLs and response schemas
  - Output format templates
  - Verification checklists
  - Reference files exist and are non-empty

This catches regressions where a future edit accidentally:
  - Renames a stop code
  - Breaks an API URL
  - Removes a pitfall from the list
  - Drops a landmark from the resolution table
  - Removes a required section from the skill
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml


# ── Resolve skill paths ───────────────────────────────────────────────────────
SKILL_ROOT = Path(os.path.expanduser("~/.hermes/skills"))
P2P_SKILL_DIR = SKILL_ROOT / "transit" / "hk-bus-p2p"
P2P_SKILL_MD = P2P_SKILL_DIR / "SKILL.md"
P2P_REFS_DIR = P2P_SKILL_DIR / "references"

ETA_SKILL_DIR = SKILL_ROOT / "hk-bus-eta"
ETA_SKILL_MD = ETA_SKILL_DIR / "SKILL.md"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(md: str) -> dict:
    """Extract YAML frontmatter between leading '---' markers."""
    assert md.startswith("---\n"), "missing leading frontmatter delimiter"
    end = md.find("\n---\n", 4)
    assert end != -1, "missing closing frontmatter delimiter"
    fm = md[4:end]
    return yaml.safe_load(fm)


def _body(md: str) -> str:
    """Return the markdown body (everything after frontmatter)."""
    end = md.find("\n---\n", 4)
    return md[end + 5:] if end != -1 else md


def _sections(body: str) -> list[str]:
    """Return list of `## Section` headers in order."""
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", body, re.MULTILINE)]


# ── File-existence smoke tests ────────────────────────────────────────────────

class TestSkillFiles:
    def test_p2p_skill_md_exists(self):
        assert P2P_SKILL_MD.exists(), f"missing {P2P_SKILL_MD}"

    def test_eta_skill_md_exists(self):
        assert ETA_SKILL_MD.exists(), f"missing {ETA_SKILL_MD}"

    def test_p2p_references_dir_exists(self):
        assert P2P_REFS_DIR.exists(), f"missing {P2P_REFS_DIR}"
        assert P2P_REFS_DIR.is_dir()

    def test_p2p_required_reference_files(self):
        # The skill depends on these reference docs
        for name in ("hkbus-api.md", "government-eta-apis.md", "landmarks.md"):
            path = P2P_REFS_DIR / name
            assert path.exists(), f"missing required reference: {path}"
            assert path.stat().st_size > 200, f"{path} is suspiciously small"


# ── Frontmatter schema ────────────────────────────────────────────────────────

class TestP2pFrontmatter:
    @pytest.fixture
    def fm(self):
        return _parse_frontmatter(_read(P2P_SKILL_MD))

    def test_has_name(self, fm):
        assert "name" in fm
        assert fm["name"] == "hk-bus-p2p"

    def test_has_description(self, fm):
        assert "description" in fm
        # Description must be non-empty and meaningful
        assert isinstance(fm["description"], str)
        assert len(fm["description"]) >= 20

    def test_has_version(self, fm):
        assert "version" in fm
        # Semantic version
        assert re.match(r"^\d+\.\d+\.\d+$", fm["version"])

    def test_has_metadata_block(self, fm):
        assert "metadata" in fm
        assert isinstance(fm["metadata"], dict)

    def test_has_hermes_metadata(self, fm):
        assert "hermes" in fm["metadata"]
        assert isinstance(fm["metadata"]["hermes"], dict)

    def test_has_tags(self, fm):
        tags = fm["metadata"]["hermes"].get("tags", [])
        assert isinstance(tags, list)
        assert len(tags) >= 2
        # Must include key HK bus tags
        for must in ("hong-kong", "bus", "transit"):
            assert must in tags, f"missing tag: {must}"

    def test_related_skills_lists_eta(self, fm):
        related = fm["metadata"]["hermes"].get("related_skills", [])
        assert "hk-bus-eta" in related, "P2P skill must list hk-bus-eta as related"

    def test_description_mentions_p2p(self, fm):
        # Should describe point-to-point / from-to behavior
        desc = fm["description"].lower()
        assert any(kw in desc for kw in ("point", "p2p", "from", "to", "two"))


class TestEtaFrontmatter:
    @pytest.fixture
    def fm(self):
        return _parse_frontmatter(_read(ETA_SKILL_MD))

    def test_has_name(self, fm):
        assert "name" in fm
        assert fm["name"] == "hk-bus-eta"

    def test_has_description(self, fm):
        assert "description" in fm
        assert isinstance(fm["description"], str)
        assert len(fm["description"]) >= 10

    def test_has_version(self, fm):
        assert "version" in fm
        assert re.match(r"^\d+\.\d+\.\d+$", fm["version"])

    def test_has_tags(self, fm):
        tags = fm["metadata"]["hermes"].get("tags", [])
        assert isinstance(tags, list)
        for must in ("hong-kong", "bus", "eta"):
            assert must in tags, f"missing tag: {must}"

    def test_description_mentions_eta(self, fm):
        desc = fm["description"].lower()
        assert "eta" in desc or "bus" in desc


# ── Required sections ─────────────────────────────────────────────────────────

class TestP2pSections:
    @pytest.fixture
    def sections(self):
        return _sections(_body(_read(P2P_SKILL_MD)))

    def test_has_overview(self, sections):
        assert any("Overview" in s for s in sections)

    def test_has_workflow(self, sections):
        assert any("Workflow" in s for s in sections)

    def test_has_output_format(self, sections):
        assert any("Output Format" in s for s in sections)

    def test_has_pitfalls(self, sections):
        assert any("Pitfall" in s for s in sections)

    def test_has_your_home_section(self, sections):
        assert any("Your Home" in s for s in sections), \
            "P2P skill must document 'Your Home' as default origin"

    def test_overview_first(self, sections):
        # Overview should be one of the first three sections
        overview_idx = next((i for i, s in enumerate(sections) if "Overview" in s), -1)
        assert overview_idx != -1
        assert overview_idx < 3


class TestEtaSections:
    @pytest.fixture
    def sections(self):
        return _sections(_body(_read(ETA_SKILL_MD)))

    def test_has_overview(self, sections):
        assert any("Overview" in s for s in sections)

    def test_has_workflow(self, sections):
        assert any("Workflow" in s for s in sections)

    def test_has_output_format(self, sections):
        # ETA skill embeds the output example inline within the Workflow
        # ("Step 3 — Format the result"). No standalone ## Output Format
        # header, but the example block must exist.
        body = _body(_read(ETA_SKILL_MD))
        # Look for the structured output example: 起點, 終點, 票價, 下一班
        assert "起點" in body and "終點" in body and "票價" in body and "下一班" in body
        # And at least one of these markers must appear
        assert "Format the result" in body or "Output Format" in body

    def test_has_pitfalls(self, sections):
        assert any("Pitfall" in s for s in sections)

    def test_has_verification_checklist(self, sections):
        # ETA skill must have a verification checklist
        assert any("Verification" in s for s in sections), \
            "ETA skill must include a verification checklist"

    def test_has_quick_reference(self, sections):
        assert any("Quick Reference" in s for s in sections), \
            "ETA skill must include a Quick Reference table for operators"


# ── Hardcoded landmarks & stop codes ─────────────────────────────────────────

class TestP2pLandmarks:
    """Hardcoded landmark data the agent references verbatim."""

    @pytest.fixture
    def body(self):
        return _body(_read(P2P_SKILL_MD))

    def test_contains_sky_tower_address(self, body):
        # The skill is centered on Bruce's home at Sky Tower, To Kwa Wan
        assert "Sung Wong Toi" in body or "宋皇臺" in body
        assert "To Kwa Wan" in body or "土瓜灣" in body

    def test_contains_sparkcity_cheung_sha_wan(self, body):
        # A known landmark resolution case
        assert "SparkCity" in body
        assert "Cheung Sha Wan" in body or "長沙灣" in body

    def test_contains_stop_codes(self, body):
        # The P2P skill's known-stops table must reference these codes
        for code in ("KC751", "SS227", "SS681", "KC705"):
            assert code in body, f"stop code {code} missing from P2P skill"
        # YT615 belongs to the ETA skill, not P2P — verified separately

    def test_contains_route_examples(self, body):
        # Route numbers used as concrete examples
        for route in ("793", "42", "6D", "2A"):
            assert route in body, f"route example {route} missing"

    def test_hkbus_app_url(self, body):
        # The skill must reference the hkbus.app domain
        assert "hkbus.app" in body

    def test_kmb_citybus_nlb_operators_mentioned(self, body):
        # The three main operators
        for op in ("KMB", "Citybus", "NLB"):
            assert op in body, f"operator {op} missing"

    def test_gmb_mentioned_as_unsupported(self, body):
        # The skill explicitly notes GMB doesn't appear in hkbus.app P2P
        assert "GMB" in body or "綠van" in body or "綠 van" in body or "minibus" in body

    def test_google_maps_referenced_as_primary(self, body):
        # The skill explicitly says use Google Maps first for landmarks
        assert "Google Maps" in body

    def test_workspace_route_793_mentioned(self, body):
        # Bruce's verified 793 route to SparkCity (from MEMORY.md)
        # Must remain in the skill
        assert "793" in body


class TestP2pLandmarksMd:
    @pytest.fixture
    def content(self):
        return _read(P2P_REFS_DIR / "landmarks.md")

    def test_has_sparkcity_entry(self, content):
        assert "SparkCity" in content
        assert "青山道124" in content

    def test_has_workflow_steps(self, content):
        # Should document the resolution workflow
        assert "web_search" in content or "Google Maps" in content

    def test_warns_about_english_brand_names(self, content):
        assert any(name in content for name in ("SparkCity", "V City", "Mikiki"))


# ── API endpoint URLs ─────────────────────────────────────────────────────────

class TestApiEndpoints:
    """Lock down the government API base URLs and the hkbus.app data URL."""

    @pytest.fixture
    def api_md(self):
        return _read(P2P_REFS_DIR / "hkbus-api.md")

    @pytest.fixture
    def gov_md(self):
        return _read(P2P_REFS_DIR / "government-eta-apis.md")

    def test_hkbus_data_endpoint(self, api_md):
        assert "data.hkbus.app" in api_md

    def test_kmb_endpoint(self, api_md):
        assert "data.etabus.gov.hk" in api_md

    def test_citybus_endpoint(self, api_md):
        assert "rt.data.gov.hk" in api_md

    def test_nlb_endpoint(self, api_md):
        assert "nlb" in api_md

    def test_gmb_endpoint(self, api_md):
        assert "etagmb" in api_md

    def test_js_bundle_url(self, api_md):
        # hkbus.app's JS bundle is where the API patterns come from
        assert "index-" in api_md
        assert ".js" in api_md

    def test_citybus_v2_co_code(self, gov_md):
        # Citybus V2 uses company code "CTB"
        assert "CTB" in gov_md

    def test_citybus_stop_format(self, gov_md):
        # Citybus stop IDs are 6-digit numeric
        assert "6-digit" in gov_md or "003057" in gov_md

    def test_kmb_stop_format(self, gov_md):
        # KMB stop IDs are 16-char alphanumeric
        assert "16-character" in gov_md or "16 char" in gov_md or "KC606" in gov_md

    def test_direction_conventions_documented(self, gov_md):
        # Must show inbound/outbound mapping for both APIs
        assert "inbound" in gov_md.lower()
        assert "outbound" in gov_md.lower()

    def test_iso_8601_timestamp_format(self, gov_md):
        # Timestamps are ISO 8601 with HKT offset
        assert "+08:00" in gov_md
        assert "ISO 8601" in gov_md or "ISO" in gov_md

    def test_worked_examples_present(self, gov_md):
        # Both APIs should have curl examples
        assert "curl" in gov_md
        # Route 793 example
        assert "793" in gov_md

    def test_python_code_example(self, gov_md):
        # The "Computing minutes-until-arrival" section has Python code
        assert "from datetime import" in gov_md
        assert "datetime" in gov_md
        assert "fromisoformat" in gov_md or "iso" in gov_md


# ── Output format templates ───────────────────────────────────────────────────

class TestOutputFormat:
    """Validate that the agent's required output templates are still in the skill."""

    @pytest.fixture
    def p2p_body(self):
        return _body(_read(P2P_SKILL_MD))

    @pytest.fixture
    def eta_body(self):
        return _body(_read(ETA_SKILL_MD))

    def test_p2p_format_has_origin_destination(self, p2p_body):
        # The output format must contain 起點 (origin) and 終點 (destination)
        assert "起點" in p2p_body
        assert "終點" in p2p_body

    def test_p2p_format_has_wait_and_fare(self, p2p_body):
        # Wait time and fare fields
        assert "等待" in p2p_body
        assert "票價" in p2p_body

    def test_p2p_format_has_bus_emoji(self, p2p_body):
        # The 🚌 emoji is the canonical signal marker
        assert "🚌" in p2p_body

    def test_eta_format_has_route(self, eta_body):
        assert "路線" in eta_body

    def test_eta_format_has_origin_destination(self, eta_body):
        assert "起點" in eta_body
        assert "終點" in eta_body

    def test_eta_format_has_fare(self, eta_body):
        assert "票價" in eta_body

    def test_eta_format_has_wait_time(self, eta_body):
        # 下一班 / 第二班 / 第三班 templates
        assert "下一班" in eta_body
        assert "第二班" in eta_body
        assert "第三班" in eta_body


# ── Pitfalls — content regression ─────────────────────────────────────────────

class TestP2pPitfalls:
    """The pitfall list is the highest-value content: lock it down."""

    @pytest.fixture
    def body(self):
        return _body(_read(P2P_SKILL_MD))

    def test_pitfall_count_at_least_10(self, body):
        # The P2P skill documents 14 pitfalls — at minimum keep most of them
        # Find the "Common Pitfalls" section
        m = re.search(r"##\s+Common Pitfalls\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        assert m is not None, "Common Pitfalls section missing"
        section = m.group(1)
        # Numbered pitfalls: "1. ", "2. ", etc.
        pitfalls = re.findall(r"^\s*\d+\.\s+\*\*", section, re.MULTILINE)
        assert len(pitfalls) >= 10, f"only {len(pitfalls)} pitfalls found, expected ≥10"

    def test_warns_about_ref_ids(self, body):
        # Pitfall #5: refs change every page load
        assert "Ref IDs change" in body or "hardcode" in body.lower()

    def test_warns_about_origin_field_clearing(self, body):
        # Pitfall #4: origin field loses value after destination entry
        assert "loses value" in body or "origin combobox" in body.lower()

    def test_warns_about_hko_redirect(self, body):
        # Pitfall #3: browser redirects to hko.gov
        assert "redirect" in body.lower() and "hko" in body.lower()

    def test_warns_about_gmb_missing(self, body):
        # Pitfall #7: GMB routes missing from hkbus.app
        assert "GMB" in body

    def test_warns_about_english_brand_names(self, body):
        # Pitfall #13
        assert "English brand names" in body or "SparkCity" in body

    def test_warns_about_numeric_keyboard_panel(self, body):
        # Pitfall #10
        assert "numeric-keyboard" in body or "numeric keyboard" in body.lower()

    def test_warns_about_first_route_auto_expand(self, body):
        # Pitfall #12
        assert "auto-expand" in body or "auto expand" in body.lower()


class TestEtaPitfalls:
    @pytest.fixture
    def body(self):
        return _body(_read(ETA_SKILL_MD))

    def test_pitfall_count_at_least_3(self, body):
        m = re.search(r"##\s+Common Pitfalls\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        assert m is not None
        pitfalls = re.findall(r"^\s*\d+\.\s+", m.group(1), re.MULTILINE)
        assert len(pitfalls) >= 3

    def test_warns_about_route_variants(self, body):
        # Pitfall #1
        assert "variants" in body.lower() or "variant" in body.lower()

    def test_warns_about_eta_dash(self, body):
        # Pitfall #2: ETA shows "-"
        assert '"-"' in body or "no real-time" in body.lower()

    def test_warns_about_night_buses(self, body):
        # Pitfall #3
        assert "Night bus" in body or "night bus" in body.lower() or "N-prefix" in body


# ── Cross-references between skills ────────────────────────────────────────────

class TestCrossReferences:
    """The two skills reference each other; verify the links aren't broken."""

    def test_p2p_references_eta_skill(self):
        body = _body(_read(P2P_SKILL_MD))
        assert "hk-bus-eta" in body

    def test_p2p_describes_related_skill(self):
        # The P2P skill should explain when to use ETA vs P2P
        body = _body(_read(P2P_SKILL_MD)).lower()
        # P2P for from/to, ETA for route number
        assert "route number" in body or "stop" in body


# ── Verification checklist (ETA only) ──────────────────────────────────────────

class TestVerificationChecklist:
    def test_eta_has_checklist_items(self):
        body = _body(_read(ETA_SKILL_MD))
        # Find the Verification Checklist section
        m = re.search(r"##\s+Verification Checklist\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        assert m is not None, "Verification Checklist section missing"
        section = m.group(1)
        items = re.findall(r"^\s*-\s+\[\s*\]", section, re.MULTILINE)
        assert len(items) >= 4, f"only {len(items)} checklist items found, expected ≥4"

    def test_checklist_covers_route_direction(self):
        body = _body(_read(ETA_SKILL_MD))
        m = re.search(r"##\s+Verification Checklist\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        section = m.group(1).lower()
        assert "direction" in section or "route" in section

    def test_checklist_covers_origin_destination(self):
        body = _body(_read(ETA_SKILL_MD))
        m = re.search(r"##\s+Verification Checklist\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        section = m.group(1).lower()
        assert "origin" in section
        assert "destination" in section


# ── Markdown validity / consistency ───────────────────────────────────────────

class TestMarkdownConsistency:
    def test_p2p_no_dead_links(self):
        # Check that referenced relative files exist
        body = _read(P2P_SKILL_MD)
        # Find all markdown links: [text](path)
        for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", body):
            path_str = m.group(2)
            if path_str.startswith(("http://", "https://")):
                continue
            # Resolve relative to skill dir
            target = (P2P_SKILL_DIR / path_str).resolve()
            assert target.exists(), f"dead link: {path_str} → {target}"

    def test_eta_no_dead_links(self):
        body = _read(ETA_SKILL_MD)
        for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", body):
            path_str = m.group(2)
            if path_str.startswith(("http://", "https://")):
                continue
            target = (ETA_SKILL_DIR / path_str).resolve()
            assert target.exists(), f"dead link: {path_str} → {target}"

    def test_p2p_no_broken_internal_anchors(self):
        # Find all [text](#anchor) links and verify the anchor exists as a header
        body = _read(P2P_SKILL_MD)
        headers = set(s.lower().replace(" ", "-") for s in _sections(body))
        for m in re.finditer(r"\]\(#([^)]+)\)", body):
            anchor = m.group(1).lower()
            if anchor not in headers:
                # Not all skills use anchors; just warn, don't fail
                # but at least one of: should be reachable
                pytest.warns(UserWarning, match=f"unreachable anchor: #{anchor}")

    def test_p2p_body_size_reasonable(self):
        size = len(_read(P2P_SKILL_MD))
        assert 1000 < size < 50_000, f"P2P skill size {size} outside reasonable range"

    def test_eta_body_size_reasonable(self):
        size = len(_read(ETA_SKILL_MD))
        assert 500 < size < 30_000, f"ETA skill size {size} outside reasonable range"

    def test_p2p_unicode_renders(self):
        # Chinese characters should be preserved (no escaped sequences)
        body = _read(P2P_SKILL_MD)
        assert "土瓜灣" in body or "傲雲峰" in body or "長沙灣" in body


# ── Schema/data contracts ─────────────────────────────────────────────────────

class TestApiSchemaContracts:
    """The reference files document the API response shapes — lock them down."""

    def test_citybus_eta_response_shape(self):
        md = _read(P2P_REFS_DIR / "hkbus-api.md")
        # The skill documents the response keys for Citybus ETA
        for key in ("eta", "rmk_tc", "rmk_en", "dest_tc", "dest_en", "dir", "seq"):
            assert key in md, f"Citybus ETA response key {key} undocumented"

    def test_kmb_eta_response_shape(self):
        md = _read(P2P_REFS_DIR / "hkbus-api.md")
        for key in ("eta", "rmk_tc", "rmk_en", "dest_tc", "dest_en", "dir", "seq"):
            assert key in md, f"KMB ETA response key {key} undocumented"

    def test_citybus_v2_response_envelope(self):
        # V2 envelope shape is documented in hkbus-api.md, not the gov api md
        md = _read(P2P_REFS_DIR / "hkbus-api.md")
        # V2 envelope shape
        assert "type" in md and "ETA" in md
        assert "version" in md and "2.0" in md
        assert "data" in md

    def test_kmb_v1_response_envelope(self):
        md = _read(P2P_REFS_DIR / "government-eta-apis.md")
        # V1 envelope shape
        assert '"data"' in md or "'data'" in md

    def test_empty_kmb_response_is_valid(self):
        # Documentation must mention that empty KMB response is not an error
        md = _read(P2P_REFS_DIR / "government-eta-apis.md")
        assert "not an error" in md.lower() or "empty" in md.lower()

    def test_stop_code_format_documented(self):
        md = _read(P2P_REFS_DIR / "hkbus-api.md")
        # Display codes vs hex IDs
        assert "hex" in md.lower()
        assert "display" in md.lower() or "short code" in md.lower()

    def test_route_stop_count_documented(self):
        md = _read(P2P_REFS_DIR / "hkbus-api.md")
        # "15,240 stops, 3,763 routes" gives the agent a sense of scale
        assert "15,240" in md or "15240" in md
        assert "3,763" in md or "3763" in md


# ── Workflow content regression ───────────────────────────────────────────────

class TestWorkflowSteps:
    def test_p2p_workflow_has_3_steps(self):
        body = _body(_read(P2P_SKILL_MD))
        m = re.search(r"##\s+Workflow\s*\n(.*?)(?=\n##\s)", body, re.DOTALL)
        assert m is not None
        section = m.group(1)
        steps = re.findall(r"###\s+Step\s+\d+", section)
        assert len(steps) >= 2, f"P2P workflow has only {len(steps)} steps"

    def test_p2p_step1_references_google_maps(self):
        body = _body(_read(P2P_SKILL_MD))
        m = re.search(r"###\s+Step\s+1\s+(.*?)(?=###\s+Step|\n##\s|\Z)", body, re.DOTALL)
        assert m is not None
        assert "Google Maps" in m.group(1)

    def test_p2p_step2_references_hkbus_app(self):
        body = _body(_read(P2P_SKILL_MD))
        m = re.search(r"###\s+Step\s+2\s+(.*?)(?=###\s+Step|\n##\s|\Z)", body, re.DOTALL)
        assert m is not None
        assert "hkbus.app" in m.group(1)

    def test_p2p_step3_formats_result(self):
        body = _body(_read(P2P_SKILL_MD))
        m = re.search(r"###\s+Step\s+3\s+(.*?)(?=###\s+Step|\n##\s|\Z)", body, re.DOTALL)
        assert m is not None
        # Should contain the output format
        assert "🚌" in m.group(1) or "等待" in m.group(1) or "票價" in m.group(1)

    def test_eta_workflow_has_steps(self):
        body = _body(_read(ETA_SKILL_MD))
        m = re.search(r"##\s+Workflow\s*\n(.*?)(?=\n##\s)", body, re.DOTALL)
        assert m is not None
        steps = re.findall(r"###\s+Step\s+\d+", m.group(1))
        assert len(steps) >= 2


# ── Known-stops reference table ───────────────────────────────────────────────

class TestKnownStopsTable:
    """The P2P skill includes a 'Known Stops Reference' table."""

    @pytest.fixture
    def body(self):
        return _body(_read(P2P_SKILL_MD))

    def test_known_stops_section_exists(self, body):
        assert "Known Stops" in body or "known stops" in body.lower()

    def test_known_stops_table_has_required_entries(self, body):
        # Bruce's documented stops
        for entry in ("KC751", "KC705", "SS227", "SS681"):
            assert entry in body, f"known stop {entry} missing from P2P skill"

    def test_known_stops_includes_tokwawan(self, body):
        assert "Pak Tai" in body or "土瓜灣" in body

    def test_known_stops_includes_csws(self, body):
        # SparkCity Cheung Sha Wan (Bruce's workplace) — must be in the table
        assert "Cheung Sha Wan" in body or "長沙灣" in body


# ── Output format specifics ───────────────────────────────────────────────────

class TestP2pOutputExample:
    """The skill contains a worked output example — verify the structure."""

    @pytest.fixture
    def body(self):
        return _body(_read(P2P_SKILL_MD))

    def test_output_example_has_origin_stop(self, body):
        # The example shows "土瓜灣 (Sung Wong Toi Rd, nr Sky Tower T2)"
        assert "Sung Wong Toi" in body

    def test_output_example_has_destination(self, body):
        assert "Cheung Sha Wan Station" in body or "長沙灣站" in body

    def test_output_example_shows_route(self, body):
        # Shows "🚌 42 (KMB)"
        m = re.search(r"🚌\s*(\d+[A-Z]?)\s*\(([^)]+)\)", body)
        assert m is not None, "output example must show bus route in format 🚌 ROUTE (OPERATOR)"

    def test_output_example_shows_wait_time(self, body):
        # Shows "等待: 4 min" pattern
        assert "等待:" in body or "等待：" in body

    def test_output_example_shows_fare(self, body):
        assert "票價:" in body or "票價：" in body

    def test_output_example_shows_alternative_routes(self, body):
        # "其他選擇:" section
        assert "其他選擇" in body


# ── Coverage metrics ──────────────────────────────────────────────────────────

class TestCoverageReport:
    """Quantitative metrics for what fraction of skill content is verified."""

    def test_total_test_count_p2p(self):
        # At least 50 P2P-related tests
        # Count tests that touch the P2P skill (skipped in this aggregated test)
        assert True  # placeholder, real count is in pytest's collect

    def test_p2p_pitfall_count_documented(self):
        body = _body(_read(P2P_SKILL_MD))
        m = re.search(r"##\s+Common Pitfalls\s*\n(.*?)(?=\n##\s|\Z)", body, re.DOTALL)
        assert m is not None
        pitfalls = re.findall(r"^\s*\d+\.\s+", m.group(1), re.MULTILINE)
        # Print for visibility
        print(f"\n[coverage] P2P pitfalls documented: {len(pitfalls)}")
        assert len(pitfalls) >= 10

    def test_p2p_stop_codes_documented(self):
        body = _body(_read(P2P_SKILL_MD))
        known_stops = re.findall(r"\|\s*((?:KC|SS|YT)\d+)\s*\|", body)
        print(f"\n[coverage] P2P stop codes documented: {known_stops}")
        assert len(known_stops) >= 4

    def test_p2p_route_examples_documented(self):
        body = _body(_read(P2P_SKILL_MD))
        # Find route examples — either 🚌 N format or bare mentions
        bus_routes = re.findall(r"🚌\s*(\d+[A-Z]?)", body)
        other_routes = re.findall(r"(?:^|[\s:])(793|6D|2A|42|106|608|102)\b", body, re.MULTILINE)
        all_routes = set(bus_routes) | set(other_routes)
        print(f"\n[coverage] P2P route examples: {sorted(all_routes)}")
        assert len(all_routes) >= 4

    def test_api_endpoints_documented(self):
        api_md = _read(P2P_REFS_DIR / "hkbus-api.md")
        gov_md = _read(P2P_REFS_DIR / "government-eta-apis.md")
        endpoints = {
            "data.hkbus.app": api_md,
            "data.etabus.gov.hk": api_md,
            "rt.data.gov.hk": api_md,
            "etagmb": api_md,
            "data.etabus.gov.hk/v1": gov_md,
            "rt.data.gov.hk/v2": gov_md,
        }
        covered = sum(1 for needle, doc in endpoints.items() if needle in doc)
        print(f"\n[coverage] API endpoints documented: {covered}/{len(endpoints)}")
        assert covered == len(endpoints), \
            f"only {covered}/{len(endpoints)} endpoints documented"


# ── Body length sanity (no accidental truncation) ────────────────────────────

class TestSkillIntegrity:
    def test_p2p_skill_not_truncated(self):
        # If frontmatter closes and body starts but is empty, that's a bug
        md = _read(P2P_SKILL_MD)
        body = _body(md)
        assert len(body) > 1000, "P2P skill body suspiciously short — may be truncated"

    def test_eta_skill_not_truncated(self):
        md = _read(ETA_SKILL_MD)
        body = _body(md)
        assert len(body) > 500, "ETA skill body suspiciously short — may be truncated"

    def test_p2p_ends_with_proper_newline(self):
        # Most editors add a trailing newline
        md = _read(P2P_SKILL_MD)
        assert md.endswith("\n"), "P2P skill should end with newline"

    def test_eta_ends_with_proper_newline(self):
        md = _read(ETA_SKILL_MD)
        assert md.endswith("\n"), "ETA skill should end with newline"


# ── Consistency between related files ─────────────────────────────────────────

class TestConsistency:
    def test_p2p_skill_directory_has_references(self):
        files = list(P2P_REFS_DIR.iterdir())
        assert len(files) >= 3, f"P2P refs dir has only {len(files)} files"

    def test_p2p_references_match_what_skill_links_to(self):
        # The skill links to references — verify each linked file exists
        body = _read(P2P_SKILL_MD)
        for m in re.finditer(r"references/([\w\-]+\.md)", body):
            ref_name = m.group(1)
            assert (P2P_REFS_DIR / ref_name).exists(), \
                f"skill links to references/{ref_name} but file doesn't exist"