# jetbrains-copr

`jetbrains-copr` automates JetBrains Linux repackaging for COPR. It checks the JetBrains releases API for multiple configured products, downloads official Linux archives, verifies upstream checksums when available, builds RPMs for `x86_64` and `aarch64`, publishes binary RPMs to GitHub Releases, and submits an SRPM to the COPR project `cubewhy/jetbrains`.

The project is intentionally config-driven and practical. It does not attempt native builds. It only repackages official upstream archives, which makes cross-architecture packaging feasible on a single CI runner.

## Features

- Detects updates for multiple JetBrains products from a JSON config file
- Supports explicit per-product metadata such as executable name, desktop file name, icon path, and StartupWMClass
- Handles `x86_64` and `aarch64` independently based on upstream availability
- Verifies upstream SHA256 checksums when JetBrains provides checksum URLs
- Builds binary RPMs and an SRPM from a generated Jinja2 spec file
- Publishes binary RPMs to deterministic GitHub Releases
- Submits the SRPM to COPR with `copr-cli`
- Tracks processed versions in `state/versions.json`
- Provides a local CLI for `check` and `build`
- Includes unit tests and GitHub Actions workflows

## Requirements

- Linux environment
- Python 3.12+
- `uv`
- `rpmbuild` available in `PATH` for real package builds
- `gh` available in `PATH` if GitHub Release publishing is enabled
- `copr-cli` available in `PATH` if COPR submission is enabled

## Local Setup With uv

```bash
uv python install 3.12
uv sync --dev --locked
```

Run the CLI with:

```bash
uv run jetbrains-copr --help
```

## Local Dry-Run Example

Dry-run fetches release metadata, resolves build plans, and renders spec files without publishing or mutating persistent state.

```bash
uv run jetbrains-copr build \
  --config config/products.json \
  --state state/versions.json \
  --output-dir dist \
  --root-dir work \
  --dry-run
```

## Local Build Example Without Publishing

This performs actual downloads, checksum verification, archive inspection, and RPM builds, but does not require GitHub or COPR credentials.

```bash
uv run jetbrains-copr build \
  --config config/products.json \
  --state state/versions.json \
  --output-dir dist \
  --root-dir work
```

## How To Configure Products

Products live in [`config/products.json`](/mnt/data/dev/projects/jetbrains-copr/config/products.json). The file is strictly validated and uses explicit product metadata because JetBrains archive naming is not uniform.

Each product entry supports:

- `code`
- `name`
- `rpm_name`
- `executable_name`
- `desktop_file_name`
- `icon_path`
- `startup_wm_class`
- `comment`
- `categories`
- `enabled`

Example shape:

```json
{
  "products": [
    {
      "code": "IIU",
      "name": "IntelliJ IDEA Ultimate",
      "rpm_name": "jetbrains-idea-ultimate",
      "executable_name": "idea",
      "desktop_file_name": "jetbrains-idea-ultimate.desktop",
      "icon_path": "bin/idea.png",
      "startup_wm_class": "jetbrains-idea",
      "comment": "JetBrains IntelliJ IDEA Ultimate IDE",
      "categories": ["Development", "IDE", "Java", "Kotlin"],
      "enabled": true
    }
  ]
}
```

## How State Tracking Works

The last fully processed upstream release per product is stored in [`state/versions.json`](/mnt/data/dev/projects/jetbrains-copr/state/versions.json). Each entry records at least:

- `version`
- `build`
- `rpm_name`
- `updated_at`

State is updated only after the full product flow succeeds:

1. Source download and checksum verification
2. RPM and SRPM build
3. Optional GitHub Release publishing
4. Optional COPR submission

If one product fails, other products continue where possible, and only successful products are written back to state.

## Required GitHub Secrets

Scheduled or manual CI runs should provide:

- `GITHUB_TOKEN`
  GitHub automatically provides this in Actions for release publishing.
- `COPR_LOGIN`
  COPR API login value.
- `COPR_USERNAME`
  COPR username.
- `COPR_TOKEN`
  COPR API token.

`copr-cli` can also use an existing standard config file. The automation only requires COPR credentials when `--publish-copr` is enabled.

## How COPR Submission Works

The repository builds binary RPMs locally for direct download and also builds an SRPM from the same generated spec. GitHub Releases receive binary RPMs only. When COPR publishing is enabled, the automation submits the SRPM to `cubewhy/jetbrains` with `copr-cli`.

This avoids uploading prebuilt binary RPMs to COPR and matches normal COPR practice.

## Troubleshooting

- `rpmbuild` missing
  Install RPM tooling before running `build` without `--dry-run`.
- `gh` missing
  Install GitHub CLI or disable `--publish-release`.
- `copr-cli` missing
  Install `copr-cli` or disable `--publish-copr`.
- Checksum verification failed
  The run stops for that product. Inspect the downloaded checksum file and upstream artifact.
- Archive layout changed
  The run stops for that product with a clear archive layout error. Review [`docs/OPERATIONS.md`](/mnt/data/dev/projects/jetbrains-copr/docs/OPERATIONS.md).
- GitHub Release already exists
  The publisher updates the release and replaces matching assets with `gh release upload --clobber`.
- State appears stale
  Validate the upstream version and compare it with [`state/versions.json`](/mnt/data/dev/projects/jetbrains-copr/state/versions.json).

## Operational Runbook

Day-to-day operations are documented in [`docs/OPERATIONS.md`](/mnt/data/dev/projects/jetbrains-copr/docs/OPERATIONS.md). It covers initial setup, first-run strategy, adding or removing products, forcing rebuilds, failure recovery, credential rotation, and state repair.
