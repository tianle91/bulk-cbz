#!/usr/bin/env python3
"""Convert each folder in a directory into a CBZ comic archive.

A CBZ file is a ZIP archive of page images. Nested libraries are packed at
the leaf folders, so ``Author/Series/Chapter/01.jpg`` becomes
``Author/Series/Chapter.cbz``.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

__version__ = "1.2.0"

IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".jxl",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
NATIVE_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
CONVERT_TARGETS = {
    "png": ".png",
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "webp": ".webp",
}
METADATA_NAMES = {"comicinfo.xml"}
DEFAULT_EXCLUDES = ("__MACOSX", "@eaDir")
PARTIAL_SUFFIX = ".cbz.partial"
CONVERT_TIMEOUT_SECONDS = 120
MAX_DEFAULT_JOBS = 8

_NATURAL_SPLIT = re.compile(r"(\d+)")
_LOG_LOCK = threading.Lock()


class BulkCbzError(Exception):
    """Raised for usage problems that should exit with a clear message."""


@dataclass
class Options:
    directory: Path
    output: Path | None = None
    dry_run: bool = False
    verbose: bool = False
    quiet: bool = False
    overwrite: bool = False
    recursive: bool = True
    all_files: bool = False
    include_hidden: bool = False
    follow_symlinks: bool = False
    extra_extensions: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    delete_folders: bool = False
    convert_to: str | None = "png"
    imagemagick: str | None = None
    jobs: int = 1


@dataclass
class FolderPlan:
    source: Path
    output: Path
    files: list[Path]


@dataclass
class PackResult:
    source: Path
    output: Path
    status: str
    file_count: int = 0
    error: str | None = None


@dataclass
class ArchiveEntry:
    source: Path
    arcname: str
    convert: bool


def natural_key(value: str) -> list[tuple[int, object]]:
    """Sort key so page2 comes before page10.

    Numbers and text are tagged so Python 3 never compares ``int`` to ``str``.
    """
    key: list[tuple[int, object]] = []
    for part in _NATURAL_SPLIT.split(value):
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.casefold()))
    return key


def natural_path_key(path: Path) -> list[tuple[int, object]]:
    key: list[tuple[int, object]] = []
    for part in path.parts:
        key.extend(natural_key(part))
        key.append((2, ""))
    return key


def normalize_extension(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext:
        raise BulkCbzError("extensions cannot be empty")
    return ext if ext.startswith(".") else f".{ext}"


def default_jobs() -> int:
    return min(MAX_DEFAULT_JOBS, os.cpu_count() or 1)


def parse_extensions(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    extensions: list[str] = []
    for value in values:
        for piece in value.split(","):
            if piece.strip():
                extensions.append(normalize_extension(piece))
    return tuple(extensions)


def is_hidden(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = Path(path.name)
    return any(part.startswith(".") for part in relative.parts)


def matches_exclude(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def normalize_convert_to(value: str) -> str:
    if value not in CONVERT_TARGETS:
        raise BulkCbzError(f"unknown convert-to format: {value}")
    return "jpeg" if value == "jpg" else value


def should_convert_file(path: Path, options: Options) -> bool:
    if options.convert_to is None:
        return False
    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return False
    return suffix not in NATIVE_IMAGE_EXTENSIONS


def converted_arcname(arcname: str, convert_to: str) -> str:
    return str(PurePosixPath(arcname).with_suffix(CONVERT_TARGETS[convert_to]))


def find_imagemagick(explicit: str | None = None) -> str | None:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    else:
        for name in ("magick", "convert"):
            found = shutil.which(name)
            if found:
                candidates.append(found)
    for command in candidates:
        try:
            proc = subprocess.run(
                [command, "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        details = f"{proc.stdout}{proc.stderr}"
        if proc.returncode == 0 and "ImageMagick" in details:
            return command
    return None


def convert_image(path: Path, convert_to: str, magick: str) -> bytes:
    output = {
        "png": ["-alpha", "set", "PNG32:-"],
        "jpeg": [
            "-background",
            "white",
            "-alpha",
            "remove",
            "-alpha",
            "off",
            "-quality",
            "90",
            "JPEG:-",
        ],
        "webp": ["-quality", "90", "WEBP:-"],
    }[convert_to]
    cmd = [magick, f"{path.resolve()}[0]", "-auto-orient", *output]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=CONVERT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise BulkCbzError(f"ImageMagick timed out converting {path}") from exc
    if proc.returncode != 0 or not proc.stdout:
        err = proc.stderr.decode("utf-8", errors="replace").strip() or "no image data written"
        raise BulkCbzError(f"ImageMagick failed to convert {path}: {err}")
    return proc.stdout


def is_packable_file(path: Path, options: Options) -> bool:
    if not path.is_file():
        return False
    if path.is_symlink() and not options.follow_symlinks:
        return False
    if not options.include_hidden and path.name.startswith("."):
        return False
    if options.all_files:
        return path.suffix.lower() != ".cbz" and not path.name.endswith(PARTIAL_SUFFIX)
    suffix = path.suffix.lower()
    extra = options.extra_extensions
    if suffix in IMAGE_EXTENSIONS or suffix in extra:
        return True
    return path.name.casefold() in METADATA_NAMES


def collect_files(folder: Path, options: Options, names: Sequence[str] | None = None) -> list[Path]:
    if names is None:
        try:
            with os.scandir(folder) as iterator:
                names = [
                    entry.name
                    for entry in iterator
                    if not entry.is_dir(follow_symlinks=False)
                ]
        except OSError:
            return []
    files = [folder / name for name in names if is_packable_file(folder / name, options)]
    files.sort(key=lambda path: natural_key(path.name))
    return files


def should_skip_dir(path: Path, root: Path, options: Options) -> bool:
    if path == root:
        return True
    if matches_exclude(path.name, options.exclude):
        return True
    if not options.include_hidden and is_hidden(path, root):
        return True
    if not options.follow_symlinks and path.is_symlink():
        return True
    if options.output is not None and path == options.output:
        return True
    return False


def discover_folders(
    root: Path, options: Options, file_cache: dict[Path, list[Path]] | None = None
) -> list[Path]:
    if file_cache is None:
        file_cache = {}
    if not options.recursive:
        folders: list[Path] = []
        try:
            with os.scandir(root) as iterator:
                entries = [
                    (
                        entry.name,
                        Path(entry.path),
                        entry.is_dir(follow_symlinks=options.follow_symlinks),
                    )
                    for entry in iterator
                ]
        except OSError as exc:
            raise BulkCbzError(f"cannot read {root}: {exc}") from exc
        entries.sort(key=lambda item: natural_key(item[0]))
        for _name, path, is_dir in entries:
            if is_dir and not should_skip_dir(path, root, options):
                folders.append(path)
        return folders

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(
        root,
        followlinks=options.follow_symlinks,
        topdown=True,
    ):
        current = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not should_skip_dir(current / name, root, options)
        ]
        dirnames.sort(key=natural_key)
        if current == root:
            continue
        found.append(current)
        file_cache[current] = collect_files(current, options, filenames)
    found.sort(key=natural_path_key)
    with_images = [folder for folder in found if count_images(file_cache[folder], options) > 0]
    image_set = set(with_images)
    image_leaves = select_leaves(with_images)
    empty_leaves = [folder for folder in select_leaves(found) if folder not in image_set]
    selected = image_leaves + empty_leaves
    selected.sort(key=natural_path_key)
    return selected


def select_leaves(folders: Sequence[Path]) -> list[Path]:
    """Return folders that have no descendant in ``folders``.

    After a natural-path sort, a parent is immediately followed by a descendant
    if one exists, so this is linear in the number of folders.
    """
    ordered = sorted(folders, key=natural_path_key)
    leaves: list[Path] = []
    for index, folder in enumerate(ordered):
        prefix = str(folder) + os.sep
        if index + 1 < len(ordered) and str(ordered[index + 1]).startswith(prefix):
            continue
        leaves.append(folder)
    return leaves


def is_image_page(path: Path, options: Options) -> bool:
    if path.name.casefold() in METADATA_NAMES:
        return False
    suffix = path.suffix.lower()
    extra = options.extra_extensions
    return suffix in IMAGE_EXTENSIONS or suffix in extra


def count_images(files: Sequence[Path], options: Options) -> int:
    return sum(1 for path in files if is_image_page(path, options))


def output_path_for(folder: Path, root: Path, options: Options) -> Path:
    if options.output is None:
        return folder.parent / f"{folder.name}.cbz"
    relative = folder.relative_to(root)
    return options.output / relative.parent / f"{relative.name}.cbz"


def display_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.as_posix()
    text = relative.as_posix()
    return "." if text == "." else text


def describe_plan(plan: FolderPlan, root: Path) -> str:
    source = display_path(plan.source, root)
    default_output = plan.source.parent / f"{plan.source.name}.cbz"
    if plan.output == default_output:
        return f"{source}.cbz"
    return f"{source} -> {display_path(plan.output, root)}"


def status_line(kind: str, detail: str) -> str:
    return f"{kind:<5} {detail}"


def plan_conversions(options: Options) -> list[FolderPlan]:
    root = options.directory
    file_cache: dict[Path, list[Path]] = {}
    folders = discover_folders(root, options, file_cache)
    plans: list[FolderPlan] = []
    for folder in folders:
        files = file_cache.get(folder)
        if files is None:
            files = collect_files(folder, options)
        images = count_images(files, options)
        if images == 0:
            log(status_line("warn", f"{display_path(folder, root)}: no images, skipping"), options, error=True)
            continue
        if images == 1:
            log(status_line("warn", f"{display_path(folder, root)}: only 1 image"), options, error=True)
        plans.append(
            FolderPlan(
                source=folder,
                output=output_path_for(folder, root, options),
                files=files,
            )
        )
    return plans


def arcname_for(file: Path, folder: Path) -> str:
    return PurePosixPath(file.relative_to(folder).as_posix()).as_posix()


def plan_archive_entries(
    files: Sequence[Path], folder: Path, options: Options
) -> list[ArchiveEntry]:
    used: dict[str, Path] = {}
    entries: list[ArchiveEntry] = []
    for file in files:
        name = arcname_for(file, folder)
        convert = should_convert_file(file, options)
        if convert:
            assert options.convert_to is not None
            name = converted_arcname(name, options.convert_to)
        previous = used.get(name.casefold())
        if previous is not None:
            raise BulkCbzError(
                f"duplicate archive path {name!r} from {previous} and {file}"
            )
        used[name.casefold()] = file
        entries.append(ArchiveEntry(source=file, arcname=name, convert=convert))
    return entries


def entry_log_line(entry: ArchiveEntry) -> str:
    name = entry.source.name
    if entry.convert and entry.arcname != name:
        return f"       {name} -> {entry.arcname}"
    return f"       {entry.arcname}"


def write_cbz(plan: FolderPlan, options: Options) -> list[ArchiveEntry]:
    plan.output.parent.mkdir(parents=True, exist_ok=True)
    entries = plan_archive_entries(plan.files, plan.source, options)
    magick = options.imagemagick
    if any(entry.convert for entry in entries):
        magick = magick or find_imagemagick(options.imagemagick)
        if magick is None:
            entries = [
                ArchiveEntry(
                    source=entry.source,
                    arcname=arcname_for(entry.source, plan.source),
                    convert=False,
                )
                for entry in entries
            ]
    converted = convert_pages(entries, options, magick)
    tmp_path = plan.output.with_name(plan.output.name + ".partial")
    if tmp_path.exists():
        tmp_path.unlink()
    try:
        with zipfile.ZipFile(
            tmp_path,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            for entry in entries:
                if entry.convert:
                    archive.writestr(entry.arcname, converted[entry.arcname])
                else:
                    archive.write(entry.source, arcname=entry.arcname)
        tmp_path.replace(plan.output)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    return entries


def convert_pages(
    entries: Sequence[ArchiveEntry], options: Options, magick: str | None
) -> dict[str, bytes]:
    convert_entries = [entry for entry in entries if entry.convert]
    if not convert_entries:
        return {}
    assert magick is not None and options.convert_to is not None
    convert_to = options.convert_to
    command = magick

    def work(entry: ArchiveEntry) -> tuple[str, bytes]:
        return entry.arcname, convert_image(entry.source, convert_to, command)

    converted: dict[str, bytes] = {}
    workers = min(options.jobs, len(convert_entries))
    if workers <= 1:
        for entry in convert_entries:
            name, data = work(entry)
            converted[name] = data
        return converted
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, entry) for entry in convert_entries]
        for future in as_completed(futures):
            name, data = future.result()
            converted[name] = data
    return converted


def log(message: str, options: Options, *, error: bool = False, verbose: bool = False) -> None:
    if error:
        with _LOG_LOCK:
            print(message, file=sys.stderr)
        return
    if options.quiet:
        return
    if verbose and not options.verbose:
        return
    with _LOG_LOCK:
        print(message)


def convert_folder(plan: FolderPlan, options: Options) -> PackResult:
    root = options.directory
    label = describe_plan(plan, root)
    if plan.output.exists() and not options.overwrite:
        log(status_line("skip", f"{label} (exists)"), options)
        return PackResult(
            source=plan.source,
            output=plan.output,
            status="skipped",
            file_count=len(plan.files),
        )

    if options.dry_run:
        entries = plan_archive_entries(plan.files, plan.source, options)
        log(status_line("dry", f"{label} ({len(plan.files)} files)"), options)
        for entry in entries:
            log(entry_log_line(entry), options, verbose=True)
        return PackResult(
            source=plan.source,
            output=plan.output,
            status="dry-run",
            file_count=len(plan.files),
        )

    try:
        entries = write_cbz(plan, options)
    except Exception as exc:
        log(status_line("error", f"{display_path(plan.source, root)}: {exc}"), options, error=True)
        return PackResult(
            source=plan.source,
            output=plan.output,
            status="failed",
            file_count=len(plan.files),
            error=str(exc),
        )

    log(status_line("ok", f"{label} ({len(plan.files)} files)"), options)
    for entry in entries:
        log(entry_log_line(entry), options, verbose=True)

    if options.delete_folders:
        try:
            shutil.rmtree(plan.source)
            log(status_line("rm", display_path(plan.source, root)), options)
        except OSError as exc:
            log(
                status_line(
                    "error",
                    f"{display_path(plan.source, root)}: packed, but failed to delete folder: {exc}",
                ),
                options,
                error=True,
            )
            return PackResult(
                source=plan.source,
                output=plan.output,
                status="failed",
                file_count=len(plan.files),
                error=f"packed, but failed to delete folder: {exc}",
            )

    return PackResult(
        source=plan.source,
        output=plan.output,
        status="created",
        file_count=len(plan.files),
    )


def summarize(results: Sequence[PackResult], options: Options) -> int:
    if not results:
        log(status_line("done", f"no packable folders found in {display_path(options.directory, options.directory)}"), options)
        return 0

    counts = {
        "created": 0,
        "dry-run": 0,
        "skipped": 0,
        "failed": 0,
    }
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1

    created = counts["created"]
    dry_run = counts["dry-run"]
    skipped = counts["skipped"]
    failed = counts["failed"]
    log(
        status_line(
            "done",
            f"created={created} dry-run={dry_run} skipped={skipped} failed={failed}",
        ),
        options,
    )
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bulk_cbz.py",
        description=(
            "Pack leaf chapter folders into CBZ archives. "
            "Author/Series/Chapter/01.jpg becomes Author/Series/Chapter.cbz. "
            "Only images directly inside each folder are packed, in natural order. "
            "JPEG and PNG stay as-is; other formats convert to PNG with ImageMagick "
            "when it is available."
        ),
        epilog="""
common usages:
  %(prog)s ~/Comics
      Pack every leaf chapter under a nested author/series/chapter library.

  %(prog)s ~/Comics/Author/Series --immediate
      Pack only the direct child folders of that series directory.

  %(prog)s . --dry-run --verbose
      Preview archives and the page files they would contain.

  %(prog)s ./library --output ./cbz
      Write CBZ files somewhere else and leave the source folders alone.

  %(prog)s . --overwrite --delete-folders
      Replace existing archives, then delete folders after a successful pack.

  %(prog)s . --convert-to jpeg
      Convert WebP/GIF/etc. to JPEG instead of PNG. JPEG and PNG pages stay as-is.

  %(prog)s . --no-convert
      Pack original page files without converting formats.

  %(prog)s . --jobs 4
      Pack and convert with 4 workers.

  %(prog)s . --exclude '*sample*'
      Skip folders whose names match a glob.
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Library root to scan (default: current directory)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    discovery = parser.add_argument_group("discovery")
    discovery.add_argument(
        "--immediate",
        dest="recursive",
        action="store_false",
        help="Pack only direct child folders of the given directory (default: leaf chapters)",
    )
    discovery.set_defaults(recursive=True)
    discovery.add_argument(
        "--exclude",
        action="append",
        dest="exclude",
        metavar="GLOB",
        help="Skip folder names matching this glob (repeatable; default: __MACOSX, @eaDir)",
    )
    discovery.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files and folders (names starting with a dot)",
    )
    discovery.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links when scanning folders and files",
    )

    output = parser.add_argument_group("output")
    output.add_argument(
        "-o",
        "--output",
        metavar="DIR",
        help="Write CBZ files under this directory (default: next to each folder)",
    )
    output.add_argument(
        "-j",
        "--jobs",
        type=int,
        metavar="N",
        default=None,
        help="Parallel workers for packing chapters and converting pages (default: CPU count, max 8)",
    )
    output.add_argument(
        "-f",
        "--overwrite",
        action="store_true",
        help="Replace existing CBZ files (default: skip them)",
    )
    output.add_argument(
        "--delete-folders",
        action="store_true",
        help="Delete each source folder after it is packed successfully",
    )

    images = parser.add_argument_group("images")
    images.add_argument(
        "--convert-to",
        choices=("png", "jpeg", "jpg", "webp"),
        help="Format for pages that are not JPEG or PNG (default: png). JPEG and PNG are left as-is",
    )
    images.add_argument(
        "--no-convert",
        action="store_true",
        help="Pack original page files without converting formats",
    )
    images.add_argument(
        "--imagemagick",
        metavar="CMD",
        help="ImageMagick executable to use (default: magick, then convert)",
    )
    images.add_argument(
        "--ext",
        action="append",
        dest="ext",
        metavar="EXT",
        help="Additional image extension to pack (repeatable or comma-separated)",
    )
    images.add_argument(
        "--all-files",
        action="store_true",
        help="Also pack non-image files except other CBZ archives",
    )

    logging_group = parser.add_argument_group("logging")
    logging_group.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing or deleting files",
    )
    logging_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print every file added to an archive",
    )
    logging_group.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only print errors and warnings",
    )
    return parser


def options_from_args(args: argparse.Namespace) -> Options:
    directory = Path(args.directory).expanduser().resolve()
    if not directory.exists():
        raise BulkCbzError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise BulkCbzError(f"not a directory: {directory}")

    output = Path(args.output).expanduser().resolve() if args.output else None
    if output is not None and output.exists() and not output.is_dir():
        raise BulkCbzError(f"output path is not a directory: {output}")

    if args.quiet and args.verbose:
        raise BulkCbzError("use either --quiet or --verbose, not both")
    if args.no_convert and args.convert_to:
        raise BulkCbzError("use either --convert-to or --no-convert, not both")
    if args.jobs is not None and args.jobs < 1:
        raise BulkCbzError("--jobs must be at least 1")

    extra_excludes = tuple(args.exclude) if args.exclude else ()
    exclude = DEFAULT_EXCLUDES + extra_excludes
    convert_to = None if args.no_convert else normalize_convert_to(args.convert_to or "png")
    return Options(
        directory=directory,
        output=output,
        dry_run=args.dry_run,
        verbose=args.verbose,
        quiet=args.quiet,
        overwrite=args.overwrite,
        recursive=args.recursive,
        all_files=args.all_files,
        include_hidden=args.include_hidden,
        follow_symlinks=args.follow_symlinks,
        extra_extensions=parse_extensions(args.ext),
        exclude=exclude,
        delete_folders=args.delete_folders,
        convert_to=convert_to,
        imagemagick=args.imagemagick,
        jobs=default_jobs() if args.jobs is None else args.jobs,
    )


def needs_conversion(plans: Sequence[FolderPlan], options: Options) -> bool:
    return any(
        should_convert_file(path, options)
        for plan in plans
        for path in plan.files
    )

def warn_and_skip_conversion(options: Options) -> None:
    if options.imagemagick:
        message = (
            f"ImageMagick command {options.imagemagick} is not available; "
            "packing original page files without conversion"
        )
    else:
        message = (
            "ImageMagick not available; "
            "packing original page files without conversion"
        )
    log(status_line("warn", message), options, error=True)
    options.convert_to = None


def run(options: Options) -> list[PackResult]:
    plans = plan_conversions(options)
    converting = False
    if needs_conversion(plans, options):
        magick = find_imagemagick(options.imagemagick)
        if magick:
            options.imagemagick = magick
            converting = True
        else:
            warn_and_skip_conversion(options)
    if converting or options.jobs <= 1 or options.dry_run or len(plans) <= 1:
        return [convert_folder(plan, options) for plan in plans]
    with ThreadPoolExecutor(max_workers=options.jobs) as pool:
        return list(pool.map(lambda plan: convert_folder(plan, options), plans))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        options = options_from_args(args)
        results = run(options)
    except BulkCbzError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return summarize(results, options)


if __name__ == "__main__":
    sys.exit(main())
