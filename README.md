# bulk-cbz

[![CI](https://github.com/tianle91/bulk-cbz/actions/workflows/ci.yml/badge.svg)](https://github.com/tianle91/bulk-cbz/actions/workflows/ci.yml)

Pack leaf chapter folders into CBZ archives.

```
Author/Series/Chapter 01/01.jpg  →  Author/Series/Chapter 01.cbz
Author/Series/Chapter 01/02.jpg
```

Requires Python 3.9+ and the standard library. If
[ImageMagick](https://imagemagick.org/) (`magick` or `convert`) is on your PATH,
pages that are not JPEG or PNG are converted to PNG by default. If it is not
available, the script warns and packs the original files.

```bash
python3 bulk_cbz.py --help
python3 bulk_cbz.py --version
```

## Common usages

Pack every leaf chapter under a nested library:

```bash
python3 bulk_cbz.py ~/Comics
```

Pack only the direct child folders of a series directory:

```bash
python3 bulk_cbz.py ~/Comics/Author/Series --immediate
```

Preview first, including the page list:

```bash
python3 bulk_cbz.py . --dry-run --verbose
```

Write archives somewhere else and keep the source folders:

```bash
python3 bulk_cbz.py ./library --output ./cbz
```

Replace existing archives, then delete folders after a successful pack:

```bash
python3 bulk_cbz.py . --overwrite --delete-folders
```

Convert WebP/GIF/etc. to JPEG instead of PNG (JPEG and PNG pages stay as-is):

```bash
python3 bulk_cbz.py . --convert-to jpeg
```

Pack original page files without converting formats:

```bash
python3 bulk_cbz.py . --no-convert
```

Skip folders whose names match a glob:

```bash
python3 bulk_cbz.py . --exclude '*sample*'
```

## What gets packed

By default the script:

- Walks nested `author/series/chapter` trees and packs **leaf** folders (chapters), not series or author folders
- Packs only images that sit **directly** in that folder
- Adds image pages (`jpg`, `jpeg`, `png`, `gif`, `webp`, `bmp`, `tif`, `tiff`, `avif`, `jxl`, `heic`) plus `ComicInfo.xml`
- Leaves JPEG and PNG as-is, and converts other page formats to PNG with ImageMagick when it is available. If ImageMagick is missing, it warns and packs the originals
- Sorts pages naturally, so `page2` comes before `page10`
- Stores ZIP entries uncompressed (`store`), which is typical for JPEG and PNG
- Warns when a folder has no images (skipped) or only one image (still packed)
- Skips existing CBZ files unless `--overwrite` is set
- Ignores hidden folders, `__MACOSX`, and `@eaDir`

## Options

### Discovery

| Option | Purpose |
| --- | --- |
| `directory` | Library root to scan (default: current working directory) |
| `-r`, `--recursive` | Pack leaf chapter folders (default) |
| `--immediate` | Pack only direct child folders of the given directory |
| `--exclude GLOB` | Skip matching folder names (repeatable) |
| `--include-hidden` | Include dotfiles and hidden folders |
| `--follow-symlinks` | Follow symbolic links while scanning |

### Output

| Option | Purpose |
| --- | --- |
| `-o`, `--output DIR` | Write CBZ files under this directory |
| `-f`, `--overwrite` | Replace existing CBZ files |
| `--delete-folders` | Remove each source folder after it is packed |

### Images

| Option | Purpose |
| --- | --- |
| `--convert-to {png,jpeg,jpg,webp}` | Format for pages that are not JPEG or PNG (default: png) |
| `--no-convert` | Pack original page files without converting formats |
| `--imagemagick CMD` | ImageMagick executable to use |
| `--ext EXT` | Also pack this image extension (repeatable or comma-separated) |
| `--all-files` | Also pack non-image files except other CBZ archives |

### Logging

| Option | Purpose |
| --- | --- |
| `-n`, `--dry-run` | Show what would happen without writing |
| `-v`, `--verbose` / `-q`, `--quiet` | Page-level logging, or errors and warnings only |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

GitHub Actions runs that suite on every pull request across Python 3.9–3.13.
Conversion tests are skipped when ImageMagick is not installed.

## Version

`bulk_cbz.py --version` prints the current release. Release notes are in [CHANGELOG.md](CHANGELOG.md).
