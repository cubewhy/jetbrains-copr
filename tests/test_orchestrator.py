from __future__ import annotations

from pathlib import Path

from jetbrains_copr.models import Architecture
from jetbrains_copr.orchestrator import collect_release_assets
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
