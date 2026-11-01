#!/usr/bin/env python3
"""Build deterministic source release archives for Router CSI Toolkit."""

import argparse
import gzip
import hashlib
import os
import stat
import tarfile
from pathlib import Path


ARCHIVE_ROOT = "router-csi-toolkit"
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
}
EXCLUDED_FILES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _source_entries(source_root, output_dir):
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    entries = []
    for path in source_root.rglob("*"):
        relative = path.relative_to(source_root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.is_file() and (
            path.name in EXCLUDED_FILES or path.suffix in EXCLUDED_SUFFIXES
        ):
            continue
        if path == output_dir or output_dir in path.parents:
            continue
        entries.append(path)
    return sorted(entries, key=lambda path: path.relative_to(source_root).as_posix())


def _tarinfo(name, mode, epoch, is_directory=False):
    info = tarfile.TarInfo(name)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = epoch
    if is_directory:
        info.type = tarfile.DIRTYPE
        info.size = 0
    else:
        info.type = tarfile.REGTYPE
        info.size = 0
    return info


def build_release(source_root, output_dir, version, epoch=0):
    source_root = Path(source_root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    archive_path = output_dir / f"router-csi-toolkit-v{version}.tar.gz"
    checksum_path = output_dir / f"{archive_path.name}.sha256"
    temporary_path = archive_path.with_suffix(f"{archive_path.suffix}.tmp")

    with temporary_path.open("wb") as raw:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw,
            compresslevel=9,
            mtime=epoch,
        ) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                archive.addfile(_tarinfo(ARCHIVE_ROOT, 0o755, epoch, is_directory=True))
                for path in _source_entries(source_root, output_dir):
                    relative = path.relative_to(source_root).as_posix()
                    archive_name = f"{ARCHIVE_ROOT}/{relative}"
                    if path.is_dir():
                        archive.addfile(
                            _tarinfo(archive_name, 0o755, epoch, is_directory=True)
                        )
                        continue
                    file_mode = (
                        0o755 if path.stat().st_mode & stat.S_IXUSR else 0o644
                    )
                    with path.open("rb") as file_handle:
                        size = path.stat().st_size
                        info = _tarinfo(archive_name, file_mode, epoch)
                        info.size = size
                        archive.addfile(info, file_handle)

    temporary_path.replace(archive_path)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum_path.write_text(
        f"{digest}  {archive_path.name}\n",
        encoding="utf-8",
    )
    return archive_path, checksum_path, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist"),
    )
    parser.add_argument(
        "--epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
    )
    args = parser.parse_args()
    archive_path, checksum_path, digest = build_release(
        Path(__file__).resolve().parents[1],
        args.output,
        args.version,
        args.epoch,
    )
    print(f"archive: {archive_path}")
    print(f"checksum: {checksum_path}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    main()
