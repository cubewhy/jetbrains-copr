# jetbrains-copr

Unofficial Copr for JetBrains IDEs

## Usage

## Use with dnf

```shell
sudo dnf copr enable cubewhy/jetbrains
```

Then you can install any IDEs you want

```shell
# For example:
# sudo dnf install jetbrains-idea
# sudo dnf install jetbrains-pycharm
```

You can find the IDE names at [config/products.json](https://github.com/cubewhy/jetbrains-copr/blob/master/config/products.json)

# Original AIGC README

`jetbrains-copr` automates JetBrains Linux repackaging for COPR. It checks the JetBrains releases API for multiple configured products, downloads official Linux archives, verifies upstream checksums when available, builds source RPMs from a generated spec, and optionally submits the SRPM to the COPR project `cubewhy/jetbrains`.

The project is intentionally config-driven and practical. It does not attempt native builds. It only repackages official upstream archives, which makes cross-architecture packaging feasible on a single CI runner.

## Features

- Detects updates for multiple JetBrains products from a JSON config file
- Supports both stable `release` and `eap` channels per product
- Supports explicit per-product metadata such as executable name, desktop file name, icon path, and StartupWMClass
- Handles `x86_64` and `aarch64` independently based on upstream availability
- Verifies upstream SHA256 checksums when JetBrains provides checksum URLs
- Builds SRPMs from a generated Jinja2 spec file
- Submits the SRPM to COPR with `copr-cli`
- Tracks processed versions in `state/versions.json`
- Provides a local CLI for `check` and `build`
- Includes unit tests and GitHub Actions workflows

## Requirements

- Linux environment
- Python 3.12+
- `uv`
- `rpmbuild` available in `PATH` for real package builds
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
  --jobs 2 \
  --dry-run
```

## Local Build Example Without Publishing

This performs actual downloads, checksum verification, archive inspection, and SRPM builds, but does not require COPR credentials unless you also publish.

```bash
uv run jetbrains-copr build \
  --config config/products.json \
  --state state/versions.json \
  --output-dir dist \
  --root-dir work \
  --jobs 1 \
  --cleanup-after-product
```

`--jobs` parallelizes the heavy per-product build stage. COPR submission and state updates stay serialized so side effects remain deterministic. On GitHub-hosted runners, start with `--jobs 1` and `--cleanup-after-product` because JetBrains archives are large enough to exhaust disk if you retain multiple products at once.

If you also pass `--sync-state-to-git`, each successful state update is committed and pushed immediately instead of waiting for the full batch to finish.

If you run on a larger self-hosted machine, or you have measured enough free space on your runner, you can raise concurrency. For GitHub Actions:

- Manual workflow: set the `jobs` input to `6`
- Scheduled workflow: set the repository variable `JETBRAINS_COPR_JOBS=6`

## How To Configure Products

Products live in [`config/products.json`](/mnt/data/dev/projects/jetbrains-copr/config/products.json). The file is strictly validated and uses explicit product metadata because JetBrains archive naming is not uniform.

Each product entry supports:

- `code`
- `release_type`
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
      "release_type": "eap",
      "name": "IntelliJ IDEA EAP",
      "rpm_name": "jetbrains-idea-eap",
      "executable_name": "idea",
      "desktop_file_name": "jetbrains-idea-eap.desktop",
      "icon_path": "bin/idea.png",
      "startup_wm_class": "jetbrains-idea",
      "comment": "JetBrains IntelliJ IDEA EAP IDE",
      "categories": ["Development", "IDE", "Java", "Kotlin"],
      "enabled": true
    }
  ]
}
```

`release_type` is optional and defaults to `release`. Use `eap` to package JetBrains Early Access Program builds alongside stable packages. When filtering products on the CLI, you can target a specific variant with `--product <CODE>:<release_type>`, for example `--product WS:eap`.

## How State Tracking Works

The last fully processed upstream release per product is stored in [`state/versions.json`](/mnt/data/dev/projects/jetbrains-copr/state/versions.json). Each entry records at least:

- `version`
- `build`
- `rpm_name`
- `updated_at`

State is updated only after the full product flow succeeds:

1. Source download and checksum verification
2. Spec render and SRPM build
3. Optional COPR submission

If one product fails, other products continue where possible, and only successful products are written back to state.

When `--sync-state-to-git` is enabled, each successful state write is also committed and pushed right away.

## Required CI Secrets

Scheduled or manual CI runs should provide:

- `COPR_LOGIN`
  COPR API login value.
- `COPR_USERNAME`
  COPR username.
- `COPR_TOKEN`
  COPR API token.

`copr-cli` can also use an existing standard config file. The automation only requires COPR credentials when `--publish-copr` is enabled.

## How COPR Submission Works

The repository builds an SRPM from the generated spec and, when COPR publishing is enabled, submits that SRPM to `cubewhy/jetbrains` with `copr-cli`.

This avoids building or distributing prebuilt binary RPMs outside COPR and matches normal COPR practice.

## Troubleshooting

- `rpmbuild` missing
  Install RPM tooling before running `build` without `--dry-run`.
- `copr-cli` missing
  Install `copr-cli` or disable `--publish-copr`.
- Checksum verification failed
  The run stops for that product. Inspect the downloaded checksum file and upstream artifact.
- Archive layout changed
  The run stops for that product with a clear archive layout error. Review [`docs/OPERATIONS.md`](/mnt/data/dev/projects/jetbrains-copr/docs/OPERATIONS.md).
- State appears stale
  Validate the upstream version and compare it with [`state/versions.json`](/mnt/data/dev/projects/jetbrains-copr/state/versions.json).

## Operational Runbook

Day-to-day operations are documented in [`docs/OPERATIONS.md`](/mnt/data/dev/projects/jetbrains-copr/docs/OPERATIONS.md). It covers initial setup, first-run strategy, adding or removing products, forcing rebuilds, failure recovery, credential rotation, and state repair.
