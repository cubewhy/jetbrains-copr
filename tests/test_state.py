from __future__ import annotations

from datetime import date

from jetbrains_copr.models import ProductConfig, ReleaseInfo, StateFile
from jetbrains_copr.state import release_matches_state, update_state_for_release


def make_product() -> ProductConfig:
    return ProductConfig(
        code="IIU",
        name="IntelliJ IDEA Ultimate",
        rpm_name="jetbrains-idea-ultimate",
        executable_name="idea",
        desktop_file_name="jetbrains-idea-ultimate.desktop",
        icon_path="bin/idea.png",
        startup_wm_class="jetbrains-idea",
        comment="JetBrains IntelliJ IDEA Ultimate IDE",
        categories=["Development", "IDE"],
        enabled=True,
    )


def make_release(version: str, build: str) -> ReleaseInfo:
    return ReleaseInfo(
        code="IIU",
        version=version,
        build=build,
        release_date=date(2026, 3, 25),
        notes_url=None,
        downloads={},
    )


def test_release_matches_state_only_for_same_version_and_build():
    state = StateFile()
    product = make_product()
    release = make_release("2026.1", "261.22158.277")
    update_state_for_release(state, product, release)

    assert release_matches_state(state, release) is True
    assert release_matches_state(state, make_release("2026.1.1", "261.22158.277")) is False
    assert release_matches_state(state, make_release("2026.1", "261.22158.300")) is False


def test_update_state_for_release_records_rpm_name():
    state = StateFile()
    product = make_product()
    release = make_release("2026.1", "261.22158.277")

    update_state_for_release(state, product, release)

    assert state.products["IIU"].rpm_name == "jetbrains-idea-ultimate"
    assert state.products["IIU"].version == "2026.1"
