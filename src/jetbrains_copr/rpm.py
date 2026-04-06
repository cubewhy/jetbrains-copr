"""RPM source preparation and build helpers."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from jetbrains_copr.errors import PackagingError
from jetbrains_copr.http import RetryingHttpClient
from jetbrains_copr.models import ARCHITECTURE_ORDER, Architecture, ProductConfig, ReleaseInfo
from jetbrains_copr.util import ensure_directory, format_rpm_changelog_date, require_command, sanitize_rpm_release, sanitize_rpm_version, sanitize_tag_component, tail_lines, utcnow


CHECKSUM_PATTERN = re.compile(r"^([0-9a-fA-F]{64})(?:\s+.+)?$")


@dataclass(frozen=True)
class PreparedSource:
    """Prepared upstream source metadata for one architecture."""

    architecture: Architecture
    archive_path: Path
    archive_name: str
    source_url: str


@dataclass(frozen=True)
class BuildArtifacts:
    """Local paths for rendered specs and built RPM artifacts."""

    spec_path: Path
    srpm_path: Path | None
    binary_rpms: dict[Architecture, Path]
    artifact_dir: Path


class RpmBuilder:
    """Prepare upstream sources and build RPM packages."""

    def __init__(self, template_path: Path) -> None:
        self._template_path = template_path
        self._environment = Environment(
            loader=FileSystemLoader(str(template_path.parent)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    def plan_source_name(self, product: ProductConfig, architecture: Architecture, source_url: str) -> str:
        """Create a unique local source file name from the upstream URL."""

        basename = Path(urlparse(source_url).path).name
        if not basename:
            raise PackagingError(f"Source URL does not contain a file name: {source_url}")
        return f"{product.code}-{architecture.value}-{basename}"

    def prepare_sources(
        self,
        *,
        product: ProductConfig,
        release: ReleaseInfo,
        architectures: list[Architecture],
        sources_dir: Path,
        http_client: RetryingHttpClient,
    ) -> dict[Architecture, PreparedSource]:
        """Download, verify, and inspect upstream archives."""

        ensure_directory(sources_dir)
        prepared: dict[Architecture, PreparedSource] = {}
        for architecture in architectures:
            download = release.downloads.get(architecture)
            if download is None:
                raise PackagingError(
                    f"{product.code} does not provide a {architecture.value} Linux download for {release.version}."
                )

            archive_name = self.plan_source_name(product, architecture, download.link)
            archive_path = sources_dir / archive_name
            http_client.download_file(download.link, archive_path)

            if download.checksum_link:
                checksum_path = sources_dir / f"{archive_name}.sha256"
                http_client.download_file(download.checksum_link, checksum_path)
                verify_checksum_file(archive_path, checksum_path)

            inspect_archive_layout(archive_path, product.executable_name)

            prepared[architecture] = PreparedSource(
                architecture=architecture,
                archive_path=archive_path,
                archive_name=archive_name,
                source_url=download.link,
            )

        return prepared

    def render_spec(
        self,
        *,
        product: ProductConfig,
        release: ReleaseInfo,
        architectures: list[Architecture],
        source_files: dict[Architecture, PreparedSource | str],
        destination: Path,
    ) -> Path:
        """Render a product-specific RPM spec."""

        template = self._environment.get_template(self._template_path.name)
        rendered = template.render(
            rpm_name=product.rpm_name,
            rpm_version=sanitize_rpm_version(release.version),
            rpm_release=f"1.{sanitize_rpm_release(release.build)}",
            name=product.name,
            executable_name=product.executable_name,
            desktop_file_name=product.desktop_file_name,
            icon_path=product.icon_path,
            startup_wm_class=product.startup_wm_class,
            comment=product.comment,
            categories_entry=";".join(product.categories) + ";",
            changelog_date=format_rpm_changelog_date(utcnow()),
            exclusive_arches=[arch.value for arch in architectures],
            source_files={
                arch.value: {
                    "archive_name": value.archive_name if isinstance(value, PreparedSource) else value,
                }
                for arch, value in source_files.items()
            },
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        return destination

    def build_srpm(self, *, spec_path: Path, topdir: Path) -> Path:
        """Build an SRPM from the rendered spec."""

        require_command("rpmbuild")
        self._run_rpmbuild(["-bs", str(spec_path)], topdir=topdir)
        built = list((topdir / "SRPMS").glob("*.src.rpm"))
        if len(built) != 1:
            raise PackagingError(f"Expected exactly one SRPM in {topdir / 'SRPMS'}, found {len(built)}.")
        return built[0]

    def build_binary_rpm(self, *, spec_path: Path, topdir: Path, architecture: Architecture) -> Path:
        """Build a binary RPM for one target architecture."""

        require_command("rpmbuild")
        self._run_rpmbuild(
            ["--target", architecture.rpm_target, "-bb", str(spec_path)],
            topdir=topdir,
        )
        built = list((topdir / "RPMS" / architecture.value).glob("*.rpm"))
        if len(built) != 1:
            raise PackagingError(
                f"Expected exactly one {architecture.value} RPM in {topdir / 'RPMS' / architecture.value}, found {len(built)}."
            )
        return built[0]

    def export_artifacts(
        self,
        *,
        product: ProductConfig,
        release: ReleaseInfo,
        spec_path: Path,
        srpm_path: Path | None,
        binary_rpms: dict[Architecture, Path],
        output_dir: Path,
    ) -> BuildArtifacts:
        """Copy rendered artifacts into the final output directory."""

        release_id = f"{sanitize_tag_component(release.version)}-{sanitize_tag_component(release.build)}"
        artifact_dir = ensure_directory(output_dir / product.rpm_name / release_id)
        exported_spec = artifact_dir / spec_path.name
        shutil.copy2(spec_path, exported_spec)

        exported_srpm: Path | None = None
        if srpm_path is not None:
            exported_srpm = artifact_dir / srpm_path.name
            shutil.copy2(srpm_path, exported_srpm)

        exported_rpms: dict[Architecture, Path] = {}
        for architecture in ARCHITECTURE_ORDER:
            source_path = binary_rpms.get(architecture)
            if source_path is None:
                continue
            destination = artifact_dir / source_path.name
            shutil.copy2(source_path, destination)
            exported_rpms[architecture] = destination

        return BuildArtifacts(
            spec_path=exported_spec,
            srpm_path=exported_srpm,
            binary_rpms=exported_rpms,
            artifact_dir=artifact_dir,
        )

    def _run_rpmbuild(self, arguments: list[str], *, topdir: Path) -> None:
        ensure_directory(topdir / "BUILD")
        ensure_directory(topdir / "BUILDROOT")
        ensure_directory(topdir / "RPMS")
        ensure_directory(topdir / "SOURCES")
        ensure_directory(topdir / "SPECS")
        ensure_directory(topdir / "SRPMS")

        command = ["rpmbuild", "--define", f"_topdir {topdir}", *arguments]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            details = "\n".join(
                part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part
            )
            raise PackagingError(f"rpmbuild failed with exit code {completed.returncode}.\n{details}")


def extract_checksum_from_text(text: str) -> str:
    """Extract a SHA256 digest from a checksum file."""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = CHECKSUM_PATTERN.match(line)
        if match:
            return match.group(1).lower()
    raise PackagingError("Checksum file did not contain a valid SHA256 digest.")


def verify_checksum_file(archive_path: Path, checksum_path: Path) -> None:
    """Verify an archive against a checksum file."""

    expected = extract_checksum_from_text(checksum_path.read_text(encoding="utf-8"))
    digest = sha256()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise PackagingError(
            f"Checksum verification failed for {archive_path.name}: expected {expected}, got {actual}."
        )


def inspect_archive_layout(archive_path: Path, executable_name: str) -> str:
    """Validate the archive layout and required executable."""

    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            names = [member.name for member in archive.getmembers() if member.name and member.name != "."]
    except (tarfile.TarError, OSError) as exc:
        raise PackagingError(f"Archive {archive_path} could not be read as tar.gz: {exc}") from exc

    top_levels: set[str] = set()
    normalized_names: set[str] = set()
    for name in names:
        normalized = name.lstrip("./")
        if not normalized:
            continue
        if normalized.startswith("../") or "/../" in normalized or normalized.startswith("/"):
            raise PackagingError(f"Archive {archive_path.name} contains unsafe path entries.")
        normalized_names.add(normalized)
        top_levels.add(normalized.split("/", 1)[0])

    if len(top_levels) != 1:
        raise PackagingError(
            f"Archive {archive_path.name} must contain exactly one top-level directory, found {sorted(top_levels)}."
        )

    top_level = next(iter(top_levels))
    expected_executable = f"{top_level}/bin/{executable_name}"
    if expected_executable not in normalized_names:
        raise PackagingError(
            f"Archive {archive_path.name} did not contain expected executable {expected_executable}."
        )

    return top_level
