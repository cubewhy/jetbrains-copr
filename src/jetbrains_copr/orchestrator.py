"""Planning and execution orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging

from jetbrains_copr.config import load_products_config
from jetbrains_copr.copr import CoprPublisher
from jetbrains_copr.errors import ApiError, ConfigError, PackagingError, PublishingError, SetupError
from jetbrains_copr.github_release import GitHubReleasePublisher
from jetbrains_copr.http import RetryingHttpClient
from jetbrains_copr.jetbrains_api import JetBrainsReleaseClient
from jetbrains_copr.models import ARCHITECTURE_ORDER, Architecture, ProductConfig, ReleaseInfo, StateEntry
from jetbrains_copr.rpm import BuildArtifacts, RpmBuilder
from jetbrains_copr.state import load_state, release_matches_state, save_state, update_state_for_release
from jetbrains_copr.util import ensure_directory, sanitize_tag_component


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductEvaluation:
    """Per-product check result."""

    product: ProductConfig
    status: str
    reason: str | None
    release: ReleaseInfo | None
    state_entry: StateEntry | None
    available_architectures: list[Architecture]
    selected_architectures: list[Architecture]
    needs_build: bool


@dataclass(frozen=True)
class BuildSummary:
    """Summary of a build command execution."""

    successful_products: list[str]
    failed_products: list[str]
    skipped_products: list[str]

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_products)


def build_check_report(
    *,
    config_path: Path,
    state_path: Path,
    product_filters: list[str] | None = None,
    architecture_filters: list[Architecture] | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Resolve current product status and return machine-readable JSON data."""

    evaluations = evaluate_products(
        config_path=config_path,
        state_path=state_path,
        product_filters=product_filters,
        architecture_filters=architecture_filters,
        force=force,
    )
    return {
        "products": [
            {
                "code": evaluation.product.code,
                "name": evaluation.product.name,
                "rpm_name": evaluation.product.rpm_name,
                "enabled": evaluation.product.enabled,
                "status": evaluation.status,
                "reason": evaluation.reason,
                "needs_build": evaluation.needs_build,
                "available_architectures": [arch.value for arch in evaluation.available_architectures],
                "selected_architectures": [arch.value for arch in evaluation.selected_architectures],
                "release": _serialize_release(evaluation.release),
                "state": _serialize_state(evaluation.state_entry),
            }
            for evaluation in evaluations
        ]
    }


def evaluate_products(
    *,
    config_path: Path,
    state_path: Path,
    product_filters: list[str] | None = None,
    architecture_filters: list[Architecture] | None = None,
    force: bool = False,
) -> list[ProductEvaluation]:
    """Evaluate products without building them."""

    config = load_products_config(config_path)
    state = load_state(state_path)
    selected_products = select_products(config.products, product_filters)
    selected_architectures = normalize_architectures(architecture_filters)

    evaluations: list[ProductEvaluation] = []
    with RetryingHttpClient() as http_client:
        api_client = JetBrainsReleaseClient(http_client)
        for product in selected_products:
            if not product.enabled:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="skipped",
                        reason="product is disabled in config",
                        release=None,
                        state_entry=state.products.get(product.code),
                        available_architectures=[],
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            try:
                release = api_client.fetch_latest_release(product.code)
            except ApiError as exc:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="error",
                        reason=str(exc),
                        release=None,
                        state_entry=state.products.get(product.code),
                        available_architectures=[],
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            if release is None:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="skipped",
                        reason="JetBrains API returned no releases for this product",
                        release=None,
                        state_entry=state.products.get(product.code),
                        available_architectures=[],
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            available = release.available_architectures()
            if not available:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="skipped",
                        reason="latest release has no Linux downloads",
                        release=release,
                        state_entry=state.products.get(product.code),
                        available_architectures=[],
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            selected = [arch for arch in selected_architectures if arch in available]
            if not selected:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="skipped",
                        reason="requested architectures are not available for this release",
                        release=release,
                        state_entry=state.products.get(product.code),
                        available_architectures=available,
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            already_processed = release_matches_state(state, release)
            needs_build = force or not already_processed
            status = "update-available" if needs_build else "up-to-date"
            reason = "force rebuild requested" if force and already_processed else None
            evaluations.append(
                ProductEvaluation(
                    product=product,
                    status=status,
                    reason=reason,
                    release=release,
                    state_entry=state.products.get(product.code),
                    available_architectures=available,
                    selected_architectures=selected,
                    needs_build=needs_build,
                )
            )

    return evaluations


def run_build(
    *,
    config_path: Path,
    state_path: Path,
    output_dir: Path,
    root_dir: Path,
    publish_release: bool,
    publish_copr: bool,
    product_filters: list[str] | None = None,
    architecture_filters: list[Architecture] | None = None,
    dry_run: bool = False,
    allow_dry_run_state_write: bool = False,
    force: bool = False,
    github_repository: str | None = None,
    copr_project: str = "cubewhy/jetbrains",
) -> BuildSummary:
    """Execute the build flow for every selected product."""

    if dry_run:
        publish_release = False
        publish_copr = False

    evaluations = evaluate_products(
        config_path=config_path,
        state_path=state_path,
        product_filters=product_filters,
        architecture_filters=architecture_filters,
        force=force,
    )
    state = load_state(state_path)
    builder = RpmBuilder(template_path=Path("packaging/jetbrains-rpm.spec.j2"))

    github_publisher = GitHubReleasePublisher() if publish_release else None
    copr_publisher = CoprPublisher() if publish_copr else None

    successful: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    ensure_directory(output_dir)
    ensure_directory(root_dir)

    with RetryingHttpClient() as http_client:
        for evaluation in evaluations:
            product = evaluation.product
            product_label = f"{product.code} ({product.rpm_name})"

            if evaluation.status == "error":
                LOGGER.error("Skipping %s because update detection failed: %s", product_label, evaluation.reason)
                failed.append(product.code)
                continue

            if not evaluation.needs_build:
                LOGGER.info("Skipping %s: %s", product_label, evaluation.reason or evaluation.status)
                skipped.append(product.code)
                continue

            release = evaluation.release
            if release is None:
                LOGGER.error("Skipping %s because no release metadata was available.", product_label)
                failed.append(product.code)
                continue

            LOGGER.info(
                "Processing %s version %s build %s for architectures %s",
                product_label,
                release.version,
                release.build,
                ", ".join(arch.value for arch in evaluation.selected_architectures),
            )

            work_dir = root_dir / product.rpm_name / f"{sanitize_tag_component(release.version)}-{sanitize_tag_component(release.build)}"
            topdir = work_dir / "rpmbuild"
            sources_dir = topdir / "SOURCES"
            specs_dir = topdir / "SPECS"
            spec_path = specs_dir / f"{product.rpm_name}.spec"

            source_plan: dict[Architecture, str] = {
                arch: builder.plan_source_name(product, arch, release.downloads[arch].link)
                for arch in evaluation.selected_architectures
            }

            try:
                builder.render_spec(
                    product=product,
                    release=release,
                    architectures=evaluation.selected_architectures,
                    source_files=source_plan,
                    destination=spec_path,
                )

                if dry_run:
                    exported = builder.export_artifacts(
                        product=product,
                        release=release,
                        spec_path=spec_path,
                        srpm_path=None,
                        binary_rpms={},
                        output_dir=output_dir,
                    )
                    LOGGER.info("Dry-run rendered spec for %s at %s", product_label, exported.spec_path)
                    if allow_dry_run_state_write:
                        update_state_for_release(state, product, release)
                        save_state(state_path, state)
                    skipped.append(product.code)
                    continue

                prepared_sources = builder.prepare_sources(
                    product=product,
                    release=release,
                    architectures=evaluation.selected_architectures,
                    sources_dir=sources_dir,
                    http_client=http_client,
                )
                for prepared in prepared_sources.values():
                    target = sources_dir / prepared.archive_name
                    if prepared.archive_path != target:
                        target.write_bytes(prepared.archive_path.read_bytes())

                builder.render_spec(
                    product=product,
                    release=release,
                    architectures=evaluation.selected_architectures,
                    source_files=prepared_sources,
                    destination=spec_path,
                )

                srpm_path = builder.build_srpm(spec_path=spec_path, topdir=topdir)
                binary_rpms = {
                    architecture: builder.build_binary_rpm(
                        spec_path=spec_path,
                        topdir=topdir,
                        architecture=architecture,
                    )
                    for architecture in evaluation.selected_architectures
                }
                exported = builder.export_artifacts(
                    product=product,
                    release=release,
                    spec_path=spec_path,
                    srpm_path=srpm_path,
                    binary_rpms=binary_rpms,
                    output_dir=output_dir,
                )

                if github_publisher is not None:
                    if not github_repository:
                        raise ConfigError(
                            "GitHub Release publishing is enabled, but no GitHub repository was provided."
                        )
                    github_publisher.publish(
                        repository=github_repository,
                        tag=build_release_tag(product, release),
                        title=f"{product.name} {release.version} ({release.build})",
                        notes=build_release_notes(product, release, exported),
                        assets=collect_release_assets(exported),
                    )

                if copr_publisher is not None:
                    if exported.srpm_path is None:
                        raise PackagingError("SRPM was not built, so COPR submission cannot continue.")
                    copr_publisher.publish(project=copr_project, srpm_path=exported.srpm_path)

                update_state_for_release(state, product, release)
                save_state(state_path, state)
                successful.append(product.code)
                LOGGER.info("Completed %s.", product_label)
            except (PackagingError, PublishingError, SetupError, ConfigError) as exc:
                LOGGER.error("Product %s failed: %s", product_label, exc)
                failed.append(product.code)
                continue

    if not successful and not failed:
        LOGGER.info("No updates found.")

    return BuildSummary(
        successful_products=successful,
        failed_products=failed,
        skipped_products=skipped,
    )


def select_products(products: list[ProductConfig], filters: list[str] | None) -> list[ProductConfig]:
    """Apply product filters by code or rpm_name."""

    if not filters:
        return products

    normalized_filters = {item.strip() for item in filters if item.strip()}
    selected = [
        product
        for product in products
        if product.code in normalized_filters or product.rpm_name in normalized_filters
    ]
    found_tokens = {product.code for product in selected} | {product.rpm_name for product in selected}
    missing = sorted(token for token in normalized_filters if token not in found_tokens)
    if missing:
        raise ConfigError(f"Unknown product filters: {', '.join(missing)}")
    return selected


def normalize_architectures(architectures: list[Architecture] | None) -> list[Architecture]:
    """Return requested architectures in deterministic order."""

    if not architectures:
        return ARCHITECTURE_ORDER.copy()
    requested = set(architectures)
    return [arch for arch in ARCHITECTURE_ORDER if arch in requested]


def build_release_tag(product: ProductConfig, release: ReleaseInfo) -> str:
    """Generate a deterministic Git tag for GitHub Releases."""

    return "-".join(
        [
            sanitize_tag_component(product.rpm_name),
            sanitize_tag_component(release.version),
            f"b{sanitize_tag_component(release.build)}",
        ]
    )


def build_release_notes(product: ProductConfig, release: ReleaseInfo, artifacts: BuildArtifacts) -> str:
    """Render GitHub Release notes."""

    lines = [
        f"# {product.name}",
        "",
        f"- Version: `{release.version}`",
        f"- Build: `{release.build}`",
        f"- Release date: `{release.release_date.isoformat()}`",
        f"- Architectures: {', '.join(arch.value for arch in artifacts.binary_rpms)}",
        f"- RPM name: `{product.rpm_name}`",
    ]
    if release.notes_url:
        lines.append(f"- Upstream notes: {release.notes_url}")
    lines.extend(
        [
            "",
            "Artifacts in this release were generated from official JetBrains Linux archives.",
        ]
    )
    return "\n".join(lines)


def collect_release_assets(artifacts: BuildArtifacts) -> list[Path]:
    """Return GitHub Release assets in a predictable order.

    SRPMs are intentionally excluded. They are built for COPR submission, while
    GitHub Releases are used for direct end-user RPM downloads.
    """

    assets: list[Path] = []
    for architecture in ARCHITECTURE_ORDER:
        asset = artifacts.binary_rpms.get(architecture)
        if asset is not None:
            assets.append(asset)
    return assets


def _serialize_release(release: ReleaseInfo | None) -> dict[str, object] | None:
    if release is None:
        return None
    return {
        "version": release.version,
        "build": release.build,
        "date": release.release_date.isoformat(),
        "notes_url": release.notes_url,
        "downloads": {
            architecture.value: {
                "link": download.link,
                "checksum_link": download.checksum_link,
                "size": download.size,
            }
            for architecture, download in release.downloads.items()
        },
    }


def _serialize_state(entry: StateEntry | None) -> dict[str, object] | None:
    if entry is None:
        return None
    return {
        "version": entry.version,
        "build": entry.build,
        "rpm_name": entry.rpm_name,
        "updated_at": entry.updated_at.isoformat(),
    }
