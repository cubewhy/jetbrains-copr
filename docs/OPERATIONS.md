# Operations Guide

## Initial Setup

1. Create the GitHub repository and push this tree.
2. Ensure the COPR project `cubewhy/jetbrains` already exists.
3. Add repository secrets:
   - `COPR_LOGIN`
   - `COPR_USERNAME`
   - `COPR_TOKEN`
4. Confirm GitHub Actions has `contents: write`.
5. Review [`config/products.json`](/mnt/data/dev/projects/jetbrains-copr/config/products.json) and disable any products you do not want to publish yet.
6. Run a manual dry-run workflow first.

## First Run Strategy

Use a staged rollout instead of enabling everything at once.

1. Run `uv run jetbrains-copr check` locally and review the JSON output.
2. Run `uv run jetbrains-copr build --dry-run`.
3. Run `uv run jetbrains-copr build --product IIU` without publishing.
4. Inspect the generated RPM and SRPM.
5. Repeat for other products.
6. Enable GitHub Release publishing.
7. Enable COPR publishing last.

## Adding Products

1. Add a new entry to [`config/products.json`](/mnt/data/dev/projects/jetbrains-copr/config/products.json).
2. Verify:
   - correct JetBrains API `code`
   - correct `release_type` (`release` or `eap`)
   - correct `executable_name`
   - correct `icon_path`
   - correct `startup_wm_class`
3. Run:

```bash
uv run jetbrains-copr check --config config/products.json
uv run jetbrains-copr build --config config/products.json --product <CODE> --dry-run
```

If you configure both stable and EAP variants for the same product code, you can target one of them explicitly with `--product <CODE>:<release_type>`, for example `--product WS:eap`.

4. If dry-run looks correct, run a real local build for that product.

## Removing Products

Set `enabled` to `false` first. This preserves history in state while preventing future builds. Remove the entry later only after you no longer need the configuration.

## Forcing Rebuilds

Use `--force` when the upstream `version` and `build` match the saved state but you need to regenerate artifacts.

Example:

```bash
uv run jetbrains-copr build --product IIU --force
```

Typical reasons:

- a GitHub Release was deleted or corrupted
- the spec template changed
- COPR submission failed after local packaging succeeded

## Recovering From Failed Releases

If GitHub Release publishing partially succeeded:

1. Re-run the build with `--force --publish-release`.
2. The publisher will reuse the same tag and replace matching assets.
3. If the existing release contains bad assets and needs manual cleanup, delete the bad assets or delete the release entirely, then rerun.

If COPR submission failed:

1. Fix credentials or COPR-side issues.
2. Re-run with `--force --publish-copr`.
3. The local state will only advance after the rerun succeeds.

## Checking Logs

Local runs emit structured operator-oriented logs to standard error. In GitHub Actions, review the `build` step log first. Common failure points are:

- JetBrains API response changes
- checksum download failure
- unexpected archive layout
- missing `gh` or `copr-cli`
- missing credentials when publishing is enabled

## Rotating COPR Credentials

1. Generate a new COPR token.
2. Update repository secrets:
   - `COPR_LOGIN`
   - `COPR_USERNAME`
   - `COPR_TOKEN`
3. Run a manual dry-run first.
4. Run a manual publish job for one product before returning to scheduled automation.

## If JetBrains Changes Archive Layout

The packager validates that each archive has a single top-level directory and that `bin/<executable_name>` exists. If JetBrains changes the archive structure:

1. Inspect the tarball manually.
2. Update the relevant product metadata in [`config/products.json`](/mnt/data/dev/projects/jetbrains-copr/config/products.json) if only the executable or icon path changed.
3. If the overall layout changed, update the archive inspection logic in [`rpm.py`](/mnt/data/dev/projects/jetbrains-copr/src/jetbrains_copr/rpm.py).
4. Run the tests and a single-product local build before resuming automation.

## If A GitHub Release Already Exists With Bad Artifacts

You have two safe options:

1. Re-run with `--force --publish-release` and let `gh release upload --clobber` replace assets with the same names.
2. Delete the release manually, then rerun the same command.

The tag name is deterministic, so reruns target the same logical release.

## If The State File Gets Out Of Sync

Symptoms usually include skipped updates that should rebuild, or repeated rebuilds of the same version.

Recovery steps:

1. Run `uv run jetbrains-copr check`.
2. Compare the reported upstream version/build with [`state/versions.json`](/mnt/data/dev/projects/jetbrains-copr/state/versions.json).
3. Correct the affected entry manually or remove it.
4. Re-run `uv run jetbrains-copr build --product <CODE> --force` if needed.

Do not blanket-delete the whole state file unless you intend to rebuild every enabled product.
