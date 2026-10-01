#!/usr/bin/env python3
"""Time bulk_cbz discovery, packing, conversion, and directory listing.

Not part of default CI. Uses only the standard library plus ImageMagick
when conversion benches run.

  python3 benchmarks/bench.py
  python3 benchmarks/bench.py --quick
  python3 benchmarks/bench.py --jobs 4 --no-listing
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bulk_cbz  # noqa: E402


@dataclass(frozen=True)
class BenchConfig:
    authors: int
    series: int
    chapters: int
    pages: int
    pack_chapters: int
    pack_pages: int
    convert_pages: int
    jobs: int
    listing: bool
    convert: bool
    page_bytes: int = 4096


@dataclass
class BenchRow:
    name: str
    count: int
    seconds: float


def preset(quick: bool, jobs: int, listing: bool, convert: bool) -> BenchConfig:
    if quick:
        return BenchConfig(
            authors=2,
            series=2,
            chapters=5,
            pages=2,
            pack_chapters=4,
            pack_pages=4,
            convert_pages=0,
            jobs=jobs,
            listing=listing,
            convert=False,
        )
    return BenchConfig(
        authors=8,
        series=4,
        chapters=25,
        pages=2,
        pack_chapters=40,
        pack_pages=15,
        convert_pages=16,
        jobs=jobs,
        listing=listing,
        convert=convert,
    )


def time_call(func):
    started = time.perf_counter()
    result = func()
    return time.perf_counter() - started, result


def quiet_call(func):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        return func()


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_library(
    root: Path,
    *,
    authors: int,
    series: int,
    chapters: int,
    pages: int,
    payload: bytes,
    suffix: str = ".jpg",
) -> int:
    count = 0
    for author in range(authors):
        for series_n in range(series):
            for chapter in range(chapters):
                folder = root / f"Author {author}" / f"Series {series_n}" / f"Chapter {chapter}"
                folder.mkdir(parents=True, exist_ok=True)
                for page in range(pages):
                    write_bytes(folder / f"{page:03d}{suffix}", payload)
                    count += 1
    return count


def listing_rows(root: Path) -> list[BenchRow]:
    rows: list[BenchRow] = []

    def walk() -> tuple[int, int]:
        dirs = files = 0
        for _dirpath, dirnames, filenames in os.walk(root):
            dirs += len(dirnames)
            files += len(filenames)
        return dirs, files

    seconds, (dirs, files) = time_call(walk)
    rows.append(BenchRow(f"os.walk listing ({dirs} dirs)", files, seconds))

    def scandir_tree(path: str) -> tuple[int, int]:
        dirs = files = 0
        with os.scandir(path) as iterator:
            for entry in iterator:
                if entry.is_dir(follow_symlinks=False):
                    child_dirs, child_files = scandir_tree(entry.path)
                    dirs += 1 + child_dirs
                    files += child_files
                else:
                    files += 1
        return dirs, files

    seconds, (dirs, files) = time_call(lambda: scandir_tree(str(root)))
    rows.append(BenchRow(f"os.scandir listing ({dirs} dirs)", files, seconds))

    find = shutil.which("find")
    if find:
        def run_find() -> int:
            proc = subprocess.run(
                [find, str(root), "-type", "f", "-print0"],
                capture_output=True,
                check=True,
            )
            return proc.stdout.count(b"\0")

        seconds, count = time_call(run_find)
        rows.append(BenchRow("find -type f -print0", count, seconds))
    else:
        rows.append(BenchRow("find (not available)", 0, 0.0))
    return rows


def write_webp_pages(folder: Path, count: int, magick: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        path = folder / f"{index:03d}.webp"
        proc = subprocess.run(
            [magick, "-size", "400x600", "xc:red", "-quality", "80", f"WEBP:{path}"],
            capture_output=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"failed to create {path}: {err}")


def pack_library(root: Path, jobs: int, extra: list[str] | None = None) -> int:
    args = [str(root), "--quiet", "--jobs", str(jobs), *(extra or [])]
    code = quiet_call(lambda: bulk_cbz.main(args))
    if code != 0:
        raise RuntimeError(f"bulk_cbz exited {code} for {args}")
    return sum(1 for path in root.rglob("*.cbz") if path.is_file())


def unlink_cbz(root: Path) -> None:
    for path in root.rglob("*.cbz"):
        path.unlink()


def run_benchmarks(config: BenchConfig) -> list[BenchRow]:
    rows: list[BenchRow] = []
    payload = b"x" * config.page_bytes
    with TemporaryDirectory() as raw:
        discovery_root = Path(raw) / "discovery"
        discovery_root.mkdir()
        files = build_library(
            discovery_root,
            authors=config.authors,
            series=config.series,
            chapters=config.chapters,
            pages=config.pages,
            payload=payload,
        )
        options = bulk_cbz.Options(
            directory=discovery_root,
            convert_to=None,
            quiet=True,
            jobs=1,
        )
        seconds, folders = time_call(
            lambda: quiet_call(lambda: bulk_cbz.discover_folders(discovery_root, options))
        )
        rows.append(
            BenchRow(
                f"discover_folders ({config.authors}x{config.series}x{config.chapters})",
                len(folders),
                seconds,
            )
        )
        seconds, plans = time_call(lambda: quiet_call(lambda: bulk_cbz.plan_conversions(options)))
        rows.append(BenchRow("plan_conversions", len(plans), seconds))

        if config.listing:
            rows.extend(listing_rows(discovery_root))

        pack_root = Path(raw) / "pack"
        pack_root.mkdir()
        build_library(
            pack_root,
            authors=1,
            series=1,
            chapters=config.pack_chapters,
            pages=config.pack_pages,
            payload=payload,
        )
        seconds, created = time_call(lambda: pack_library(pack_root, 1, ["--no-convert"]))
        rows.append(BenchRow("pack jpeg --jobs 1", created, seconds))
        unlink_cbz(pack_root)
        seconds, created = time_call(lambda: pack_library(pack_root, config.jobs, ["--no-convert"]))
        rows.append(BenchRow(f"pack jpeg --jobs {config.jobs}", created, seconds))

        magick = bulk_cbz.find_imagemagick() if config.convert and config.convert_pages else None
        if magick:
            convert_root = Path(raw) / "convert"
            write_webp_pages(convert_root / "Chapter", config.convert_pages, magick)
            seconds, created = time_call(lambda: pack_library(convert_root, 1))
            rows.append(BenchRow("convert webp --jobs 1", created, seconds))
            unlink_cbz(convert_root)
            seconds, created = time_call(lambda: pack_library(convert_root, config.jobs))
            rows.append(BenchRow(f"convert webp --jobs {config.jobs}", created, seconds))
        elif config.convert:
            rows.append(BenchRow("convert webp (ImageMagick missing)", 0, 0.0))

        rows.append(BenchRow("synthetic jpeg files created", files, 0.0))
    return rows


def format_report(config: BenchConfig, rows: list[BenchRow]) -> str:
    magick = bulk_cbz.find_imagemagick() or "not found"
    lines = [
        "bulk-cbz benchmarks",
        f"python {sys.version.split()[0]}  jobs={config.jobs}  "
        f"cpus={os.cpu_count() or 1}  ImageMagick={magick}",
        "",
        f"{'scenario':<48} {'count':>8}  {'time':>8}",
        f"{'-' * 48}  {'-' * 8}  {'-' * 8}",
    ]
    for row in rows:
        if row.seconds == 0.0 and row.name.endswith("created"):
            lines.append(f"{row.name:<48} {row.count:>8}")
            continue
        if row.seconds == 0.0 and ("not available" in row.name or "missing" in row.name):
            lines.append(f"{row.name:<48} {row.count:>8}  {'skipped':>8}")
            continue
        lines.append(f"{row.name:<48} {row.count:>8}  {row.seconds:7.3f}s")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="Smaller trees for a fast smoke run")
    parser.add_argument(
        "--jobs",
        type=int,
        metavar="N",
        default=bulk_cbz.default_jobs(),
        help="Worker count to compare against --jobs 1 (default: CPU count, max 8)",
    )
    parser.add_argument("--no-listing", action="store_true", help="Skip os.walk / os.scandir / find timings")
    parser.add_argument("--no-convert", action="store_true", help="Skip ImageMagick conversion timings")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs < 1:
        print("error: --jobs must be at least 1", file=sys.stderr)
        return 2
    config = preset(
        quick=args.quick,
        jobs=args.jobs,
        listing=not args.no_listing,
        convert=not args.no_convert,
    )
    rows = run_benchmarks(config)
    sys.stdout.write(format_report(config, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
