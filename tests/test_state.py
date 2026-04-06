from __future__ import annotations

from datetime import date

from jetbrains_copr.models import ProductConfig, ReleaseInfo, StateFile
from jetbrains_copr.state import release_matches_state, state_entry_for_product, update_state_for_release


def make_product(*, release_type: str = "release") -> ProductConfig:
    return ProductConfig(
        code="IIU",
        release_type=release_type,
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

    assert release_matches_state(state, product, release) is True
    assert release_matches_state(state, product, make_release("2026.1.1", "261.22158.277")) is False
    assert release_matches_state(state, product, make_release("2026.1", "261.22158.300")) is False


def test_release_matches_state_is_scoped_to_product_variant():
    state = StateFile()
    stable_product = make_product()
    eap_product = make_product(release_type="eap")
    release = make_release("2026.1", "261.22158.277")
    update_state_for_release(state, stable_product, release)

    assert release_matches_state(state, stable_product, release) is True
    assert release_matches_state(state, eap_product, release) is False


def test_state_entry_for_product_falls_back_to_legacy_release_key():
    state = StateFile(
        products={
            "IIU": {
                "version": "2026.1",
                "build": "261.22158.277",
                "rpm_name": "jetbrains-idea-ultimate",
                "updated_at": "2026-03-25T00:00:00Z",
            }
        }
    )

    entry = state_entry_for_product(state, make_product())

    assert entry is not None
    assert entry.version == "2026.1"


def test_update_state_for_release_records_rpm_name():
    state = StateFile()
    product = make_product()
    release = make_release("2026.1", "261.22158.277")

    update_state_for_release(state, product, release)

    assert state.products["IIU:release"].rpm_name == "jetbrains-idea-ultimate"
    assert state.products["IIU:release"].version == "2026.1"
