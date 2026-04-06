from __future__ import annotations

from datetime import date

from jetbrains_copr.util import format_rpm_changelog_date, sanitize_rpm_release, sanitize_rpm_version, sanitize_tag_component


def test_sanitize_rpm_version_replaces_invalid_characters():
    assert sanitize_rpm_version("2026.1-rc/1") == "2026.1_rc_1"


def test_sanitize_rpm_release_replaces_invalid_characters():
    assert sanitize_rpm_release("261.22158.277+test/1") == "261.22158.277+test_1"


def test_sanitize_tag_component_replaces_invalid_characters():
    assert sanitize_tag_component("2026.1 rc/1") == "2026.1-rc-1"


def test_format_rpm_changelog_date_uses_rpm_style():
    assert format_rpm_changelog_date(date(2026, 4, 6)) == "Mon Apr 06 2026"
