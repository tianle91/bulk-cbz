# bulk-cbz

[![CI](https://github.com/tianle91/bulk-cbz/actions/workflows/ci.yml/badge.svg)](https://github.com/tianle91/bulk-cbz/actions/workflows/ci.yml)

Convert every folder in a directory into a CBZ file with the same name.

A CBZ is a ZIP archive of comic pages. Point the script at a parent folder
(or run it in the current directory) and each child folder becomes
`FolderName.cbz`.

Requires Python 3.9+ and the standard library. If
[ImageMagick](https://imagemagick.org/) (`magick` or `convert`) is on your PATH,
pages that are not JPEG or PNG are converted to PNG by default. If it is not
available, the script warns and packs the original files.

```bash
python3 bulk_cbz.py --help
```

## Common usages

Pack each folder in the current directory:

```bash
python3 bulk_cbz.py
```

Pack every volume or chapter folder in a series:

```bash
python3 bulk_cbz.py ~/Comics/One-Piece
```

Preview first, including the page list:

```bash
python3 bulk_cbz.py . --dry-run --verbose
```

Write archives somewhere else and keep the source folders:

```bash
python3 bulk_cbz.py ./chapters --output ./cbz
```

Walk a nested library and only pack the lowest image folders (chapters),
not series folders that also contain a cover:

```bash
python3 bulk_cbz.py ./library --recursive --leaves-only
```

A chapter whose pages live in a subfolder still becomes one CBZ:

```bash
python3 bulk_cbz.py ./volume --include-nested
```

Replace existing archives, then delete folders after a successful pack:

```bash
python3 bulk_cbz.py . --overwrite --delete-folders
```

Skip thin chapters and names you do not want packed:

```bash
python3 bulk_cbz.py . --min-files 10 --exclude '*sample*'
```

Convert WebP/GIF/etc. to JPEG instead of PNG (JPEG and PNG pages stay as-is):

```bash
python3 bulk_cbz.py . --convert-to jpeg
```

Pack original page files without ImageMagick:

```bash
python3 bulk_cbz.py . --no-convert
```

## What gets packed

By default the script:

- Converts **immediate subfolders** of the given directory, not the directory itself
- Adds image pages (`jpg`, `jpeg`, `png`, `gif`, `webp`, `bmp`, `tif`, `tiff`, `avif`, `jxl`, `heic`) plus `ComicInfo.xml`
- Leaves JPEG and PNG pages as-is, and converts other page formats to PNG with ImageMagick when it is available (alpha is kept; use `--convert-to` or `--no-convert` to change that). If ImageMagick is missing, the script warns and packs the originals
- Sorts pages naturally, so `page2` comes before `page10`
- Stores files uncompressed (`--compression store`), which is typical for already-compressed images
- Skips existing CBZ files unless `--overwrite` is set
- Ignores hidden folders, `__MACOSX`, and `@eaDir`

## Options

| Option | Purpose |
| --- | --- |
| `directory` | Parent folder to scan (default: current working directory) |
| `-o`, `--output DIR` | Write CBZ files under this directory |
| `-n`, `--dry-run` | Show what would happen without writing |
| `-v`, `--verbose` / `-q`, `--quiet` | Page-level logging, or errors only |
| `-f`, `--overwrite` | Replace existing CBZ files |
| `-r`, `--recursive` | Convert folders at every nesting level |
| `--leaves-only` | With `--recursive`, skip folders that contain other packable folders |
| `--include-nested` | Include images from subfolders of each packed folder |
| `--all-files` | Pack every file except other CBZ archives |
| `--include-hidden` | Include dotfiles and hidden folders |
| `--follow-symlinks` | Follow symbolic links while scanning |
| `--ext EXT` | Also pack this image extension (repeatable or comma-separated) |
| `--exclude GLOB` | Skip matching folder names (repeatable) |
| `--min-files N` | Skip folders with fewer than N packable files |
| `--convert-to {png,jpeg,jpg,webp}` | Format for pages that are not JPEG or PNG (default: png) |
| `--no-convert` | Pack original page files without converting formats |
| `--imagemagick CMD` | ImageMagick executable to use |
| `--compression {store,deflate}` | ZIP compression method |
| `--delete-folders` | Remove each source folder after it is packed |

## Tests

```bash
python3 -m unittest discover -s tests -v
```

GitHub Actions runs that suite on every pull request across Python 3.9–3.13.
Conversion tests are skipped when ImageMagick is not installed.
