from __future__ import annotations

from datetime import date
import io
from pathlib import Path
import tarfile

import pytest

from jetbrains_copr.models import Architecture, ProductConfig, ReleaseInfo
from jetbrains_copr.rpm import RpmBuilder, extract_checksum_from_text, inspect_archive_layout


def _write_tar_gz(path, members):
    with tarfile.open(path, "w:gz") as archive:
        for name, content in members.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_extract_checksum_from_text_accepts_common_format():
    digest = "a" * 64
    assert extract_checksum_from_text(f"{digest}  idea-2026.1.tar.gz\n") == digest


def test_extract_checksum_from_text_rejects_malformed_text():
    with pytest.raises(Exception, match="SHA256"):
        extract_checksum_from_text("not-a-checksum\n")


def test_inspect_archive_layout_accepts_single_top_level_directory(tmp_path):
    archive_path = tmp_path / "idea.tar.gz"
    _write_tar_gz(
        archive_path,
        {
            "idea-IU-261/bin/idea": "launcher",
            "idea-IU-261/bin/idea.png": "icon",
        },
    )

    top_level = inspect_archive_layout(archive_path, "idea")

    assert top_level == "idea-IU-261"


def test_inspect_archive_layout_rejects_multiple_top_levels(tmp_path):
    archive_path = tmp_path / "broken.tar.gz"
    _write_tar_gz(
        archive_path,
        {
            "one/bin/idea": "launcher",
            "two/bin/idea": "launcher",
        },
    )

    with pytest.raises(Exception, match="one top-level directory"):
        inspect_archive_layout(archive_path, "idea")


def test_render_spec_includes_selected_architectures(tmp_path):
    template_path = tmp_path / "template.spec.j2"
    template_path.write_text("ExclusiveArch: {{ exclusive_arches | join(' ') }}\n", encoding="utf-8")
    builder = RpmBuilder(template_path=template_path)
    destination = tmp_path / "jetbrains.spec"
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
        enabled=True,
    )
    release = ReleaseInfo(
        code="IIU",
        version="2026.1",
        build="261.22158.277",
        release_date=date(2026, 3, 25),
        notes_url=None,
        downloads={},
    )

    builder.render_spec(
        product=product,
        release=release,
        architectures=[Architecture.X86_64, Architecture.AARCH64],
        source_files={
            Architecture.X86_64: "IIU-x86_64-idea-2026.1.tar.gz",
            Architecture.AARCH64: "IIU-aarch64-idea-2026.1-aarch64.tar.gz",
        },
        destination=destination,
    )

    assert "ExclusiveArch: x86_64 aarch64" in destination.read_text(encoding="utf-8")


def test_real_spec_template_escapes_percent_sequences(tmp_path):
    builder = RpmBuilder(template_path=Path("packaging/jetbrains-rpm.spec.j2"))
    destination = tmp_path / "jetbrains.spec"
    product = ProductConfig(
        code="IIU",
        name="IntelliJ IDEA Ultimate",
        rpm_name="jetbrains-idea-ultimate",
        executable_name="idea.sh",
        desktop_file_name="jetbrains-idea-ultimate.desktop",
        icon_path="bin/idea.png",
        startup_wm_class="jetbrains-idea",
        comment="JetBrains IntelliJ IDEA Ultimate IDE",
        categories=["Development", "IDE"],
        enabled=True,
    )
    release = ReleaseInfo(
        code="IIU",
        version="2026.1",
        build="261.22158.277",
        release_date=date(2026, 3, 25),
        notes_url=None,
        downloads={},
    )

    builder.render_spec(
        product=product,
        release=release,
        architectures=[Architecture.X86_64],
        source_files={Architecture.X86_64: "IIU-x86_64-idea-2026.1.tar.gz"},
        destination=destination,
    )

    rendered = destination.read_text(encoding="utf-8")

    assert "Exec=/usr/bin/jetbrains-idea-ultimate %%f" in rendered
    assert "find . -mindepth 1 -printf '/opt/jetbrains-idea-ultimate/%%P\\n'" in rendered
