"""Command line interface."""

from __future__ import annotations

from pathlib import Path
import json
import logging
import os

import typer

from jetbrains_copr.errors import JetbrainsCoprError
from jetbrains_copr.models import Architecture
from jetbrains_copr.orchestrator import build_check_report, run_build


app = typer.Typer(help="JetBrains RPM repackaging and COPR automation.")


def configure_logging() -> None:
    """Set a simple operator-friendly logging format."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@app.command()
def check(
    config_path: Path = typer.Option(Path("config/products.json"), "--config"),
    state_path: Path = typer.Option(Path("state/versions.json"), "--state"),
    product: list[str] | None = typer.Option(None, "--product"),
    architecture: list[Architecture] | None = typer.Option(None, "--arch"),
    force: bool = typer.Option(False, "--force", help="Report matching state entries as buildable."),
) -> None:
    """Print machine-readable update information as JSON."""

    configure_logging()
    try:
        report = build_check_report(
            config_path=config_path,
            state_path=state_path,
            product_filters=product,
            architecture_filters=architecture,
            force=force,
        )
    except JetbrainsCoprError as exc:
        raise typer.Exit(code=_print_error(exc))

    typer.echo(json.dumps(report, indent=2, sort_keys=True))


@app.command()
def build(
    config_path: Path = typer.Option(Path("config/products.json"), "--config"),
    state_path: Path = typer.Option(Path("state/versions.json"), "--state"),
    output_dir: Path = typer.Option(Path("dist"), "--output-dir"),
    root_dir: Path = typer.Option(Path("work"), "--root-dir"),
    publish_release: bool = typer.Option(False, "--publish-release"),
    publish_copr: bool = typer.Option(False, "--publish-copr"),
    product: list[str] | None = typer.Option(None, "--product"),
    architecture: list[Architecture] | None = typer.Option(None, "--arch"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    allow_dry_run_state_write: bool = typer.Option(False, "--allow-dry-run-state-write"),
    force: bool = typer.Option(False, "--force"),
    jobs: int = typer.Option(1, "--jobs", min=1, help="Parallel workers for the per-product build stage."),
    github_repository: str | None = typer.Option(
        None,
        "--github-repository",
        show_default="env:GITHUB_REPOSITORY",
        help="Repository in owner/name form for GitHub Releases.",
    ),
    copr_project: str = typer.Option("cubewhy/jetbrains", "--copr-project"),
) -> None:
    """Build packages and optionally publish them."""

    configure_logging()
    try:
        summary = run_build(
            config_path=config_path,
            state_path=state_path,
            output_dir=output_dir,
            root_dir=root_dir,
            publish_release=publish_release,
            publish_copr=publish_copr,
            product_filters=product,
            architecture_filters=architecture,
            dry_run=dry_run,
            allow_dry_run_state_write=allow_dry_run_state_write,
            force=force,
            jobs=jobs,
            github_repository=github_repository or os.environ.get("GITHUB_REPOSITORY"),
            copr_project=copr_project,
        )
    except JetbrainsCoprError as exc:
        raise typer.Exit(code=_print_error(exc))

    if summary.has_failures:
        raise typer.Exit(code=1)


def _print_error(exc: Exception) -> int:
    typer.echo(str(exc), err=True)
    return 1


if __name__ == "__main__":
    app()
