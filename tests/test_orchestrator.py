from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import pytest

from jetbrains_copr.errors import ConfigError
from jetbrains_copr.models import Architecture, ProductConfig, ReleaseInfo, StateFile
from jetbrains_copr.orchestrator import (
    BuildExecutionResult,
    ProductEvaluation,
    _publish_completed_result,
    cleanup_completed_product_paths,
    run_build,
    select_products,
)
from jetbrains_copr.rpm import BuildArtifacts


def test_run_build_rejects_invalid_jobs(tmp_path: Path):
    with pytest.raises(ConfigError, match="--jobs"):
        run_build(
            config_path=tmp_path / "products.json",
            state_path=tmp_path / "versions.json",
            output_dir=tmp_path / "dist",
            root_dir=tmp_path / "work",
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


def test_publish_completed_result_saves_state_before_sync_callback(tmp_path: Path):
    product = ProductConfig(
        code="IIU",
        name="IntelliJ IDEA Ultimate",
        rpm_name="jetbrains-idea-ultimate",
        executable_name="idea",
        desktop_file_name="jetbrains-idea-ultimate.desktop",
        icon_path="bin/idea.png",
        startup_wm_class="jetbrains-idea",
        comment="JetBrains IntelliJ IDEA Ultimate IDE",
        categories=["Development", "IDE"],
    )
    release = ReleaseInfo(
        code="IIU",
        version="2026.1",
        build="261.22158.277",
        release_date=date(2026, 3, 25),
        downloads={},
    )
    artifact_dir = tmp_path / "dist" / product.rpm_name
    artifact_dir.mkdir(parents=True)
    spec_path = artifact_dir / f"{product.rpm_name}.spec"
    spec_path.write_text("Name: test\n", encoding="utf-8")
    result = BuildExecutionResult(
        evaluation=ProductEvaluation(
            product=product,
            status="update-available",
            reason=None,
            release=release,
            state_entry=None,
            available_architectures=[],
            selected_architectures=[],
            needs_build=True,
        ),
        exported=BuildArtifacts(
            spec_path=spec_path,
            srpm_path=None,
            artifact_dir=artifact_dir,
        ),
        work_dir=tmp_path / "work" / product.rpm_name,
    )
    state_path = tmp_path / "state" / "versions.json"
    synced_state: dict[str, object] = {}
    successful: list[str] = []
    failed: list[str] = []

    def sync_callback(callback_product: ProductConfig, callback_release: ReleaseInfo) -> None:
        synced_state["product"] = callback_product.identity
        synced_state["release"] = callback_release.version
        synced_state["payload"] = json.loads(state_path.read_text(encoding="utf-8"))

    _publish_completed_result(
        result=result,
        copr_publisher=None,
        copr_project="cubewhy/jetbrains",
        state=StateFile(),
        state_path=state_path,
        state_sync_callback=sync_callback,
        cleanup_after_product=False,
        successful=successful,
        failed=failed,
        root_dir=tmp_path / "work",
    )

    assert successful == ["IIU"]
    assert failed == []
    assert synced_state["product"] == "IIU:release"
    assert synced_state["release"] == "2026.1"
    assert synced_state["payload"]["products"]["IIU:release"]["build"] == "261.22158.277"
