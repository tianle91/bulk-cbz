# Release notes

This project uses [semantic versioning](https://semver.org/). The current
script version is the `__version__` string in `bulk_cbz.py` (`python3 bulk_cbz.py --version`).

## [1.2.0] - Unreleased

Leaf-chapter packing, quieter logs, and faster packing.

### Added

- `-j`, `--jobs N` to set the worker count. Use `--jobs 1` on a spinning disk or network share if parallel I/O hurts.
- `benchmarks/bench.py` times discovery, packing, conversion, and `os.walk` / `os.scandir` / `find` listing on a synthetic library.

### Changed

- Default discovery walks nested `author/series/chapter` trees and packs **leaf** folders, so `Author/Series/Chapter/01.jpg` becomes `Author/Series/Chapter.cbz`.
- Leaf selection uses folders that contain images, so a chapter is still packed when it has a non-image child folder such as `notes/`.
- Empty leaf folders (and leaves with no recognized images) warn and are skipped in recursive mode as well as with `--immediate`.
- `--immediate` packs only direct children of the given directory.
- Only images that sit directly in a folder are packed.
- ZIP entries are always stored uncompressed.
- Status logs print a path relative to the scan root once (`Author/Series/Chapter.cbz`) instead of repeating long source and output directories. Verbose mode lists page filenames only.
- CLI flags are grouped into discovery, output, images, and logging.
- Discovery scans each folder once and finds leaf chapters in linear time.
- Chapters are packed in parallel, and ImageMagick conversions within a chapter run in parallel (default: CPU count, max 8).

### Removed

- `--recursive` (leaf-chapter packing is the default; use `--immediate` to opt out)
- `--leaves-only` (folded into default recursive packing)
- `--include-nested`
- `--min-files` (empty folders are skipped with a warning; a single image is packed with a warning)
- `--compression`

## [1.1.0] - 2026-10-01

Image conversion for comic-reader compatibility.

### Added

- Convert pages that are not JPEG or PNG to PNG by default, using ImageMagick (`magick` or `convert`) when it is available. Transparency is preserved for PNG.
- `--convert-to {png,jpeg,jpg,webp}` to choose the conversion target. JPEG and PNG pages stay as-is.
- `--no-convert` to pack original page files.
- `--imagemagick CMD` to select the ImageMagick executable.

### Changed

- If ImageMagick is missing, warn and pack original files instead of failing. The script does not install conversion tools.

## [1.0.0] - 2026-10-01

First release.

### Added

- `bulk_cbz.py` packs each image folder into a same-named `.cbz` archive.
- Natural page ordering (`page2` before `page10`).
- Dry-run, overwrite, output directory, excludes, and optional folder deletion.
- GitHub Actions CI across Python 3.9–3.13.
