"""Planning and execution orchestration."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
import logging
import shutil

from jetbrains_copr.config import load_products_config
from jetbrains_copr.copr import CoprPublisher
from jetbrains_copr.errors import ApiError, ConfigError, PackagingError, PublishingError, SetupError
from jetbrains_copr.github_release import GitHubReleasePublisher
from jetbrains_copr.http import RetryingHttpClient
from jetbrains_copr.jetbrains_api import JetBrainsReleaseClient
from jetbrains_copr.models import ARCHITECTURE_ORDER, Architecture, ProductConfig, ReleaseInfo, StateEntry
from jetbrains_copr.rpm import BuildArtifacts, RpmBuilder
from jetbrains_copr.state import load_state, release_matches_state, save_state, state_entry_for_product, update_state_for_release
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


@dataclass(frozen=True)
class BuildExecutionResult:
    """Result of the heavy per-product build stage."""

    evaluation: ProductEvaluation
    exported: BuildArtifacts
    work_dir: Path


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
                "release_type": evaluation.product.release_type,
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
                        state_entry=state_entry_for_product(state, product),
                        available_architectures=[],
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            try:
                release = api_client.fetch_latest_release(product.code, release_type=product.release_type)
            except ApiError as exc:
                evaluations.append(
                    ProductEvaluation(
                        product=product,
                        status="error",
                        reason=str(exc),
                        release=None,
                        state_entry=state_entry_for_product(state, product),
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
                        state_entry=state_entry_for_product(state, product),
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
                        state_entry=state_entry_for_product(state, product),
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
                        state_entry=state_entry_for_product(state, product),
                        available_architectures=available,
                        selected_architectures=[],
                        needs_build=False,
                    )
                )
                continue

            already_processed = release_matches_state(state, product, release)
            needs_build = force or not already_processed
            status = "update-available" if needs_build else "up-to-date"
            reason = "force rebuild requested" if force and already_processed else None
            evaluations.append(
                ProductEvaluation(
                    product=product,
                    status=status,
                    reason=reason,
                    release=release,
                    state_entry=state_entry_for_product(state, product),
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
    jobs: int = 1,
    cleanup_after_product: bool = False,
    github_repository: str | None = None,
    copr_project: str = "cubewhy/jetbrains",
) -> BuildSummary:
    """Execute the build flow for every selected product."""

    if jobs < 1:
        raise ConfigError("--jobs must be at least 1.")

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
    github_publisher = GitHubReleasePublisher() if publish_release else None
    copr_publisher = CoprPublisher() if publish_copr else None

    successful: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    ensure_directory(output_dir)
    ensure_directory(root_dir)

    buildable_evaluations: list[ProductEvaluation] = []
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

        buildable_evaluations.append(evaluation)

    if dry_run:
        for evaluation in buildable_evaluations:
            result = _render_dry_run_artifacts(evaluation=evaluation, output_dir=output_dir, root_dir=root_dir)
            LOGGER.info(
                "Dry-run rendered spec for %s (%s) at %s",
                evaluation.product.code,
                evaluation.product.rpm_name,
                result.exported.spec_path,
            )
            if allow_dry_run_state_write and evaluation.release is not None:
                update_state_for_release(state, evaluation.product, evaluation.release)
                save_state(state_path, state)
            if cleanup_after_product:
                cleanup_completed_product_paths(work_dir=result.work_dir, artifact_dir=result.exported.artifact_dir)
            skipped.append(evaluation.product.code)
    else:
        LOGGER.info("Running build stage with %d worker(s).", jobs)
        if jobs > 1:
            LOGGER.warning(
                "Parallel build workers > 1 increase peak disk usage because multiple JetBrains archives and build trees exist at once."
            )
        log_disk_usage("Initial free space", root_dir)
        _run_parallel_build_and_publish(
            buildable_evaluations=buildable_evaluations,
            jobs=jobs,
            root_dir=root_dir,
            output_dir=output_dir,
            github_publisher=github_publisher,
            github_repository=github_repository,
            copr_publisher=copr_publisher,
            copr_project=copr_project,
            state=state,
            state_path=state_path,
            cleanup_after_product=cleanup_after_product,
            successful=successful,
            failed=failed,
        )

    if not successful and not failed:
        LOGGER.info("No updates found.")

    return BuildSummary(
        successful_products=successful,
        failed_products=failed,
        skipped_products=skipped,
    )


def _run_parallel_build_and_publish(
    *,
    buildable_evaluations: list[ProductEvaluation],
    jobs: int,
    root_dir: Path,
    output_dir: Path,
    github_publisher: GitHubReleasePublisher | None,
    github_repository: str | None,
    copr_publisher: CoprPublisher | None,
    copr_project: str,
    state,
    state_path: Path,
    cleanup_after_product: bool,
    successful: list[str],
    failed: list[str],
) -> None:
    """Run bounded parallel builds and publish each completed result immediately."""

    if not buildable_evaluations:
        return

    max_workers = min(jobs, len(buildable_evaluations))
    pending: dict[Future[BuildExecutionResult], ProductEvaluation] = {}
    evaluation_iter = iter(buildable_evaluations)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="product-build") as executor:
        for _ in range(max_workers):
            evaluation = next(evaluation_iter, None)
            if evaluation is None:
                break
            _submit_build(executor=executor, pending=pending, evaluation=evaluation, root_dir=root_dir, output_dir=output_dir)

        while pending:
            done, _ = wait(set(pending), return_when=FIRST_COMPLETED)
            for future in done:
                evaluation = pending.pop(future)
                product = evaluation.product
                product_label = f"{product.code} ({product.rpm_name})"
                release = evaluation.release
                if release is None:
                    failed.append(product.code)
                    continue

                try:
                    result = future.result()
                    log_disk_usage(f"Built {product_label}, free space", root_dir)
                except (PackagingError, SetupError, ConfigError) as exc:
                    LOGGER.error("Product %s failed during build stage: %s", product_label, exc)
                    if cleanup_after_product:
                        cleanup_completed_product_paths(
                            work_dir=product_work_dir(product=product, release=release, root_dir=root_dir),
                            artifact_dir=product_artifact_dir(product=product, release=release, output_dir=output_dir),
                        )
                    failed.append(product.code)
                except Exception as exc:  # pragma: no cover - defensive guard
                    LOGGER.error("Product %s failed during build stage: %s", product_label, exc)
                    if cleanup_after_product:
                        cleanup_completed_product_paths(
                            work_dir=product_work_dir(product=product, release=release, root_dir=root_dir),
                            artifact_dir=product_artifact_dir(product=product, release=release, output_dir=output_dir),
                        )
                    failed.append(product.code)
                else:
                    _publish_completed_result(
                        result=result,
                        github_publisher=github_publisher,
                        github_repository=github_repository,
                        copr_publisher=copr_publisher,
                        copr_project=copr_project,
                        state=state,
                        state_path=state_path,
                        cleanup_after_product=cleanup_after_product,
                        successful=successful,
                        failed=failed,
                        root_dir=root_dir,
                    )

                next_evaluation = next(evaluation_iter, None)
                if next_evaluation is not None:
                    _submit_build(
                        executor=executor,
                        pending=pending,
                        evaluation=next_evaluation,
                        root_dir=root_dir,
                        output_dir=output_dir,
                    )


def _submit_build(
    *,
    executor: ThreadPoolExecutor,
    pending: dict[Future[BuildExecutionResult], ProductEvaluation],
    evaluation: ProductEvaluation,
    root_dir: Path,
    output_dir: Path,
) -> None:
    """Submit one build task to the executor."""

    future = executor.submit(
        _build_product_artifacts,
        evaluation=evaluation,
        output_dir=output_dir,
        root_dir=root_dir,
    )
    pending[future] = evaluation


def _publish_completed_result(
    *,
    result: BuildExecutionResult,
    github_publisher: GitHubReleasePublisher | None,
    github_repository: str | None,
    copr_publisher: CoprPublisher | None,
    copr_project: str,
    state,
    state_path: Path,
    cleanup_after_product: bool,
    successful: list[str],
    failed: list[str],
    root_dir: Path,
) -> None:
    """Publish and finalize one completed build result."""

    evaluation = result.evaluation
    product = evaluation.product
    product_label = f"{product.code} ({product.rpm_name})"
    release = evaluation.release
    if release is None:
        failed.append(product.code)
        return

    exported = result.exported

    try:
        if github_publisher is not None:
            if not github_repository:
                raise ConfigError("GitHub Release publishing is enabled, but no GitHub repository was provided.")
            release_assets = collect_release_assets(exported)
            LOGGER.info(
                "Publishing %s to GitHub Release with assets: %s",
                product_label,
                ", ".join(asset.name for asset in release_assets) or "none",
            )
            github_publisher.publish(
                repository=github_repository,
                tag=build_release_tag(product, release),
                title=f"{product.name} {release.version} ({release.build})",
                notes=build_release_notes(product, release, exported),
                assets=release_assets,
            )

        if copr_publisher is not None:
            if exported.srpm_path is None:
                raise PackagingError("SRPM was not built, so COPR submission cannot continue.")
            LOGGER.info("Submitting %s to COPR project %s", exported.srpm_path.name, copr_project)
            copr_publisher.publish(project=copr_project, srpm_path=exported.srpm_path)

        update_state_for_release(state, product, release)
        save_state(state_path, state)
        if cleanup_after_product:
            cleanup_completed_product_paths(work_dir=result.work_dir, artifact_dir=exported.artifact_dir)
            log_disk_usage(f"Cleaned {product_label}, free space", root_dir)
        successful.append(product.code)
        LOGGER.info("Completed %s.", product_label)
    except (PackagingError, PublishingError, SetupError, ConfigError) as exc:
        LOGGER.error("Product %s failed: %s", product_label, exc)
        if cleanup_after_product:
            cleanup_completed_product_paths(work_dir=result.work_dir, artifact_dir=exported.artifact_dir)
            log_disk_usage(f"Cleaned failed {product_label}, free space", root_dir)
        failed.append(product.code)


def _render_dry_run_artifacts(
    *,
    evaluation: ProductEvaluation,
    output_dir: Path,
    root_dir: Path,
) -> BuildExecutionResult:
    """Render dry-run artifacts without downloading sources or building RPMs."""

    product = evaluation.product
    release = evaluation.release
    if release is None:
        raise PackagingError(f"No release metadata was available for {product.code}.")
    product_label = f"{product.code} ({product.rpm_name})"

    builder = RpmBuilder(template_path=Path("packaging/jetbrains-rpm.spec.j2"))
    work_dir = product_work_dir(product=product, release=release, root_dir=root_dir)
    topdir = work_dir / "rpmbuild"
    specs_dir = topdir / "SPECS"
    spec_path = specs_dir / f"{product.rpm_name}.spec"
    source_plan: dict[Architecture, str] = {
        arch: builder.plan_source_name(product, arch, release.downloads[arch].link)
        for arch in evaluation.selected_architectures
    }
    builder.render_spec(
        product=product,
        release=release,
        architectures=evaluation.selected_architectures,
        source_files=source_plan,
        destination=spec_path,
    )
    exported = builder.export_artifacts(
        product=product,
        release=release,
        spec_path=spec_path,
        srpm_path=None,
        binary_rpms={},
        output_dir=output_dir,
    )
    LOGGER.info("Rendered dry-run artifacts for %s at %s", product_label, exported.artifact_dir)
    return BuildExecutionResult(evaluation=evaluation, exported=exported, work_dir=work_dir)


def _build_product_artifacts(
    *,
    evaluation: ProductEvaluation,
    output_dir: Path,
    root_dir: Path,
) -> BuildExecutionResult:
    """Build local artifacts for one product."""

    product = evaluation.product
    release = evaluation.release
    if release is None:
        raise PackagingError(f"No release metadata was available for {product.code}.")

    product_label = f"{product.code} ({product.rpm_name})"
    LOGGER.info(
        "Processing %s version %s build %s for architectures %s",
        product_label,
        release.version,
        release.build,
        ", ".join(arch.value for arch in evaluation.selected_architectures),
    )

    builder = RpmBuilder(template_path=Path("packaging/jetbrains-rpm.spec.j2"))
    work_dir = product_work_dir(product=product, release=release, root_dir=root_dir)
    topdir = work_dir / "rpmbuild"
    sources_dir = topdir / "SOURCES"
    specs_dir = topdir / "SPECS"
    spec_path = specs_dir / f"{product.rpm_name}.spec"

    source_plan: dict[Architecture, str] = {
        arch: builder.plan_source_name(product, arch, release.downloads[arch].link)
        for arch in evaluation.selected_architectures
    }
    builder.render_spec(
        product=product,
        release=release,
        architectures=evaluation.selected_architectures,
        source_files=source_plan,
        destination=spec_path,
    )

    with RetryingHttpClient() as http_client:
        prepared_sources = builder.prepare_sources(
            product=product,
            release=release,
            architectures=evaluation.selected_architectures,
            sources_dir=sources_dir,
            http_client=http_client,
        )

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
    LOGGER.info(
        "Built artifacts for %s at %s: %s",
        product_label,
        exported.artifact_dir,
        ", ".join(path.name for path in collect_release_assets(exported)) or "no release assets",
    )
    return BuildExecutionResult(evaluation=evaluation, exported=exported, work_dir=work_dir)


def cleanup_completed_product_paths(*, work_dir: Path, artifact_dir: Path) -> None:
    """Delete per-product build directories after the product is fully processed."""

    for path in [artifact_dir, work_dir]:
        try:
            if path.exists():
                shutil.rmtree(path)
                LOGGER.info("Cleaned %s", path)
        except OSError as exc:
            LOGGER.warning("Could not clean %s: %s", path, exc)


def product_work_dir(*, product: ProductConfig, release: ReleaseInfo, root_dir: Path) -> Path:
    """Return the per-product work directory."""

    return root_dir / product.rpm_name / f"{sanitize_tag_component(release.version)}-{sanitize_tag_component(release.build)}"


def product_artifact_dir(*, product: ProductConfig, release: ReleaseInfo, output_dir: Path) -> Path:
    """Return the exported artifact directory for a product release."""

    return output_dir / product.rpm_name / f"{sanitize_tag_component(release.version)}-{sanitize_tag_component(release.build)}"


def log_disk_usage(label: str, path: Path) -> None:
    """Log free disk space for the filesystem containing the given path."""

    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    LOGGER.info(
        "%s: %.2f GiB free / %.2f GiB total at %s",
        label,
        usage.free / (1024**3),
        usage.total / (1024**3),
        probe,
    )


def select_products(products: list[ProductConfig], filters: list[str] | None) -> list[ProductConfig]:
    """Apply product filters by code or rpm_name."""

    if not filters:
        return products

    normalized_filters = {item.strip() for item in filters if item.strip()}
    selected = [
        product
        for product in products
        if product.code in normalized_filters
        or product.rpm_name in normalized_filters
        or product.identity in normalized_filters
    ]
    found_tokens = (
        {product.code for product in selected}
        | {product.rpm_name for product in selected}
        | {product.identity for product in selected}
    )
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
        f"- Release type: `{product.release_type}`",
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
