from __future__ import annotations

from pathlib import Path

import pytest

from jetbrains_copr.errors import ConfigError
from jetbrains_copr.models import Architecture, ProductConfig
from jetbrains_copr.orchestrator import cleanup_completed_product_paths, collect_release_assets, run_build, select_products
from jetbrains_copr.rpm import BuildArtifacts


def test_collect_release_assets_excludes_srpm(tmp_path: Path):
    x86_rpm = tmp_path / "product.x86_64.rpm"
    aarch64_rpm = tmp_path / "product.aarch64.rpm"
    srpm = tmp_path / "product.src.rpm"
    spec = tmp_path / "product.spec"

    for path in (x86_rpm, aarch64_rpm, srpm, spec):
        path.write_text("x", encoding="utf-8")

    artifacts = BuildArtifacts(
        spec_path=spec,
        srpm_path=srpm,
        binary_rpms={
            Architecture.X86_64: x86_rpm,
            Architecture.AARCH64: aarch64_rpm,
        },
        artifact_dir=tmp_path,
    )

    assert collect_release_assets(artifacts) == [x86_rpm, aarch64_rpm]


def test_run_build_rejects_invalid_jobs(tmp_path: Path):
    with pytest.raises(ConfigError, match="--jobs"):
        run_build(
            config_path=tmp_path / "products.json",
            state_path=tmp_path / "versions.json",
            output_dir=tmp_path / "dist",
            root_dir=tmp_path / "work",
            publish_release=False,
            publish_copr=False,
            dry_run=True,
            jobs=0,
        )


def test_cleanup_completed_product_paths_removes_work_and_artifacts(tmp_path: Path):
    work_dir = tmp_path / "work" / "product"
    artifact_dir = tmp_path / "dist" / "product"
    work_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    (work_dir / "file.txt").write_text("x", encoding="utf-8")
    (artifact_dir / "file.txt").write_text("x", encoding="utf-8")

    cleanup_completed_product_paths(work_dir=work_dir, artifact_dir=artifact_dir)

    assert not work_dir.exists()
    assert not artifact_dir.exists()


def test_select_products_accepts_variant_identity_filter():
    stable = ProductConfig(
        code="WS",
        name="WebStorm",
        rpm_name="jetbrains-webstorm",
        executable_name="webstorm",
        desktop_file_name="jetbrains-webstorm.desktop",
        icon_path="bin/webstorm.png",
        startup_wm_class="jetbrains-webstorm",
        comment="JetBrains WebStorm IDE",
        categories=["Development", "IDE"],
    )
    eap = ProductConfig(
        code="WS",
        release_type="eap",
        name="WebStorm EAP",
        rpm_name="jetbrains-webstorm-eap",
        executable_name="webstorm",
        desktop_file_name="jetbrains-webstorm-eap.desktop",
        icon_path="bin/webstorm.png",
        startup_wm_class="jetbrains-webstorm",
        comment="JetBrains WebStorm EAP IDE",
        categories=["Development", "IDE"],
    )

    selected = select_products([stable, eap], ["WS:eap"])

    assert selected == [eap]
