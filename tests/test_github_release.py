from __future__ import annotations

from pathlib import Path

from jetbrains_copr.github_release import GITHUB_RELEASE_ASSET_SIZE_LIMIT_BYTES, split_release_assets_by_size


def test_split_release_assets_by_size_skips_oversized_assets(tmp_path: Path):
    small_asset = tmp_path / "small.rpm"
    large_asset = tmp_path / "large.src.rpm"

    small_asset.write_bytes(b"x")
    large_asset.write_bytes(b"x")

    original_stat = Path.stat

    def fake_stat(path: Path):
        result = original_stat(path)
        if path == large_asset:
            return result.__class__(
                (
                    result.st_mode,
                    result.st_ino,
                    result.st_dev,
                    result.st_nlink,
                    result.st_uid,
                    result.st_gid,
                    GITHUB_RELEASE_ASSET_SIZE_LIMIT_BYTES,
                    result.st_atime,
                    result.st_mtime,
                    result.st_ctime,
                )
            )
        return result

    Path.stat = fake_stat  # type: ignore[assignment]
    try:
        uploadable_assets, skipped_assets = split_release_assets_by_size([small_asset, large_asset])
    finally:
        Path.stat = original_stat  # type: ignore[assignment]

    assert uploadable_assets == [small_asset]
    assert skipped_assets == [large_asset]
