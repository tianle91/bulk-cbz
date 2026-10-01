#!/usr/bin/env python3
from __future__ import annotations

import io
import subprocess
import sys
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bulk_cbz  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOI = b"\xff\xd8"


def write_file(path: Path, content: bytes = b"page") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def zip_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def zip_bytes(path: Path, name: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name)


def png_color_type(data: bytes) -> int:
    if not data.startswith(PNG_SIGNATURE):
        raise AssertionError("not a PNG")
    return data[25]


def require_imagemagick() -> str:
    found = bulk_cbz.find_imagemagick()
    if not found:
        raise unittest.SkipTest("ImageMagick is not available")
    return found


def write_im_image(path: Path, im_format: str, *, transparent: bool = False) -> Path:
    magick = require_imagemagick()
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [magick, "-size", "4x4"]
    if transparent:
        args.extend(["xc:none", "-fill", "rgba(255,0,0,0.5)", "-draw", "point 1,1"])
    else:
        args.extend(["xc:red"])
    args.append(f"{im_format}:{path}")
    proc = subprocess.run(args, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return path


def run_cli(args: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = bulk_cbz.main(args)
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


class BulkCbzTests(unittest.TestCase):
    def test_natural_sort_orders_pages_and_volumes(self) -> None:
        self.assertLess(bulk_cbz.natural_key("page2.jpg"), bulk_cbz.natural_key("page10.jpg"))
        self.assertLess(bulk_cbz.natural_key("Vol 2"), bulk_cbz.natural_key("Vol 10"))

    def test_converts_immediate_folders_in_natural_order(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            series = root / "library"
            first = series / "Vol 1"
            second = series / "Vol 2"
            tenth = series / "Vol 10"
            write_file(first / "2.jpg")
            write_file(first / "10.jpg")
            write_file(first / "1.jpg")
            write_file(first / "ComicInfo.xml", b"<ComicInfo/>")
            write_file(first / "notes.txt")
            write_file(second / "01.png")
            write_file(tenth / "01.webp")
            write_file(series / "cover.jpg")

            code, stdout, stderr = run_cli([str(series), "--no-convert"])

            self.assertEqual(code, 0, stderr)
            self.assertTrue((series / "Vol 1.cbz").is_file())
            self.assertTrue((series / "Vol 2.cbz").is_file())
            self.assertTrue((series / "Vol 10.cbz").is_file())
            self.assertFalse((series / "library.cbz").exists())
            self.assertEqual(zip_names(series / "Vol 1.cbz"), ["1.jpg", "2.jpg", "10.jpg", "ComicInfo.xml"])
            self.assertEqual(zip_names(series / "Vol 10.cbz"), ["01.webp"])
            self.assertIn("created=3", stdout)

    def test_dry_run_does_not_write_files(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Chapter 01"
            write_file(folder / "01.jpg")

            code, stdout, _stderr = run_cli([str(root), "--dry-run", "--verbose"])

            self.assertEqual(code, 0)
            self.assertFalse((root / "Chapter 01.cbz").exists())
            self.assertIn("dry", stdout)
            self.assertIn("01.jpg", stdout)
            self.assertIn("Chapter 01.cbz", stdout)

    def test_logs_relative_cbz_path_once(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_file(root / "Author" / "Series" / "Ch01" / "01.jpg")
            write_file(root / "Author" / "Series" / "Ch01" / "02.jpg")

            code, stdout, stderr = run_cli([str(root), "--verbose"])
            self.assertEqual(code, 0, stderr)
            self.assertIn("Author/Series/Ch01.cbz", stdout)
            self.assertNotIn(str(root), stdout)
            self.assertNotIn("Ch01 -> ", stdout)
            self.assertIn("01.jpg", stdout)
            self.assertIn("02.jpg", stdout)

    def test_skip_existing_and_overwrite(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Ch01"
            write_file(folder / "01.jpg", b"old")

            self.assertEqual(run_cli([str(root)])[0], 0)
            original = (root / "Ch01.cbz").read_bytes()

            write_file(folder / "02.jpg", b"new")
            code, stdout, _stderr = run_cli([str(root)])
            self.assertEqual(code, 0)
            self.assertIn("skipped=1", stdout)
            self.assertEqual((root / "Ch01.cbz").read_bytes(), original)

            code, stdout, _stderr = run_cli([str(root), "--overwrite"])
            self.assertEqual(code, 0)
            self.assertIn("created=1", stdout)
            self.assertEqual(zip_names(root / "Ch01.cbz"), ["01.jpg", "02.jpg"])

    def test_recursive_packs_leaf_chapters_not_series(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            series = root / "Author" / "Series"
            write_file(series / "cover.jpg")
            write_file(series / "Chapter 1" / "01.jpg")
            write_file(series / "Chapter 1" / "02.jpg")
            write_file(series / "Chapter 2" / "01.jpg")
            write_file(series / "Chapter 2" / "02.jpg")

            code, stdout, stderr = run_cli([str(root)])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((series / "Chapter 1.cbz").is_file())
            self.assertTrue((series / "Chapter 2.cbz").is_file())
            self.assertFalse((root / "Author.cbz").exists())
            self.assertFalse((root / "Author" / "Series.cbz").exists())
            self.assertIn("created=2", stdout)
            self.assertNotIn("only 1 image", stderr)

    def test_immediate_packs_only_direct_children(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            series = root / "Series"
            write_file(series / "cover.jpg")
            write_file(series / "Chapter 1" / "01.jpg")
            write_file(series / "Chapter 1" / "02.jpg")

            code, stdout, stderr = run_cli([str(root), "--immediate"])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "Series.cbz").is_file())
            self.assertEqual(zip_names(root / "Series.cbz"), ["cover.jpg"])
            self.assertFalse((series / "Chapter 1.cbz").exists())
            self.assertIn("only 1 image", stderr)

    def test_nested_page_folder_is_the_packed_leaf(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            chapter = root / "Chapter 03"
            write_file(chapter / "pages" / "01.jpg")
            write_file(chapter / "pages" / "02.jpg")

            self.assertEqual(run_cli([str(root)])[0], 0)
            self.assertTrue((chapter / "pages.cbz").is_file())
            self.assertFalse((root / "Chapter 03.cbz").exists())
            self.assertEqual(zip_names(chapter / "pages.cbz"), ["01.jpg", "02.jpg"])

    def test_output_dir_exclude_and_hidden(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "src"
            output = root / "cbz"
            write_file(source / "Keep" / "01.jpg")
            write_file(source / "Keep" / "02.jpg")
            write_file(source / "Thin" / "01.jpg")
            write_file(source / "sample extras" / "01.jpg")
            write_file(source / "sample extras" / "02.jpg")
            write_file(source / ".hidden" / "01.jpg")
            write_file(source / "__MACOSX" / "01.jpg")

            code, stdout, stderr = run_cli(
                [
                    str(source),
                    "--output",
                    str(output),
                    "--exclude",
                    "*sample*",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((output / "Keep.cbz").is_file())
            self.assertTrue((output / "Thin.cbz").is_file())
            self.assertFalse((output / "sample extras.cbz").exists())
            self.assertFalse((output / ".hidden.cbz").exists())
            self.assertFalse((output / "__MACOSX.cbz").exists())
            self.assertIn("created=2", stdout)
            self.assertIn("only 1 image", stderr)

    def test_warns_when_folder_has_no_images_or_one_image(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_file(root / "Empty" / "notes.txt")
            write_file(root / "One" / "01.jpg")
            write_file(root / "Two" / "01.jpg")
            write_file(root / "Two" / "02.jpg")

            code, stdout, stderr = run_cli([str(root), "--immediate"])
            self.assertEqual(code, 0)
            self.assertFalse((root / "Empty.cbz").exists())
            self.assertTrue((root / "One.cbz").is_file())
            self.assertTrue((root / "Two.cbz").is_file())
            self.assertIn("no images, skipping", stderr)
            self.assertIn("only 1 image", stderr)
            self.assertIn("created=2", stdout)

    def test_recursive_warns_on_empty_leaf_folders(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_file(root / "Author" / "Series" / "Chapter" / "01.jpg")
            write_file(root / "Author" / "Series" / "Chapter" / "02.jpg")
            (root / "Author" / "Empty").mkdir(parents=True)
            write_file(root / "Author" / "Odd" / "notes.txt")

            code, stdout, stderr = run_cli([str(root)])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "Author" / "Series" / "Chapter.cbz").is_file())
            self.assertFalse((root / "Author" / "Empty.cbz").exists())
            self.assertFalse((root / "Author" / "Odd.cbz").exists())
            self.assertIn("Empty: no images, skipping", stderr)
            self.assertIn("Odd: no images, skipping", stderr)
            self.assertIn("created=1", stdout)

    def test_non_image_child_folder_does_not_hide_chapter(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            chapter = root / "Chapter"
            write_file(chapter / "01.jpg")
            write_file(chapter / "02.jpg")
            write_file(chapter / "notes" / "readme.txt")

            code, stdout, stderr = run_cli([str(root), "--all-files"])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "Chapter.cbz").is_file())
            self.assertEqual(zip_names(root / "Chapter.cbz"), ["01.jpg", "02.jpg"])
            self.assertFalse((chapter / "notes.cbz").exists())
            self.assertIn("notes: no images, skipping", stderr)
            self.assertIn("created=1", stdout)

    def test_delete_folders_after_success(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Done"
            write_file(folder / "01.jpg")

            code, _stdout, stderr = run_cli([str(root), "--delete-folders"])
            self.assertEqual(code, 0, stderr)
            self.assertTrue((root / "Done.cbz").is_file())
            self.assertFalse(folder.exists())

    def test_extra_extension_uses_store_compression(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Custom"
            write_file(folder / "page.cbz.bin", b"not-a-cbz-but-custom")
            write_file(folder / "page.bin", b"hello-hello-hello-hello")

            code, _stdout, stderr = run_cli([str(root), "--ext", "bin"])
            self.assertEqual(code, 0, stderr)
            archive_path = root / "Custom.cbz"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, ["page.bin", "page.cbz.bin"])
                self.assertEqual(archive.getinfo("page.bin").compress_type, zipfile.ZIP_STORED)

    def test_recursive_flag_is_not_accepted(self) -> None:
        code, _stdout, stderr = run_cli([".", "--recursive"])
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments: --recursive", stderr)

    def test_jobs_must_be_at_least_one(self) -> None:
        code, _stdout, stderr = run_cli([".", "--jobs", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--jobs must be at least 1", stderr)

    def test_select_leaves_ignores_ancestors(self) -> None:
        author = Path("/lib/Author")
        series = Path("/lib/Author/Series")
        chapter_1 = Path("/lib/Author/Series/Chapter 1")
        chapter_2 = Path("/lib/Author/Series/Chapter 2")
        other = Path("/lib/Author Extra/Ch")
        leaves = bulk_cbz.select_leaves([author, series, chapter_2, chapter_1, other])
        self.assertEqual(set(leaves), {chapter_1, chapter_2, other})
        self.assertNotIn(author, leaves)
        self.assertNotIn(series, leaves)

    def test_parallel_jobs_match_serial_archives(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for name in ("Ch 1", "Ch 2", "Ch 10"):
                write_file(root / name / "01.jpg", f"{name}-1".encode())
                write_file(root / name / "02.jpg", f"{name}-2".encode())

            self.assertEqual(run_cli([str(root), "--jobs", "1"])[0], 0)
            serial = {
                path.name: (zip_names(path), path.read_bytes())
                for path in sorted(root.glob("*.cbz"))
            }
            for path in root.glob("*.cbz"):
                path.unlink()

            code, _stdout, stderr = run_cli([str(root), "--jobs", "3"])
            self.assertEqual(code, 0, stderr)
            parallel = {
                path.name: (zip_names(path), path.read_bytes())
                for path in sorted(root.glob("*.cbz"))
            }
            self.assertEqual(parallel, serial)

    def test_folder_names_with_dots_keep_full_name(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Vol.01"
            write_file(folder / "01.jpg")

            self.assertEqual(run_cli([str(root)])[0], 0)
            self.assertTrue((root / "Vol.01.cbz").is_file())
            self.assertFalse((root / "Vol.cbz").exists())

    def test_help_lists_common_usages(self) -> None:
        code, stdout, _stderr = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("common usages", stdout)
        self.assertIn("--dry-run", stdout)
        self.assertIn("--convert-to", stdout)
        self.assertIn("--immediate", stdout)
        self.assertIn("--jobs", stdout)
        self.assertNotIn("--recursive", stdout)
        self.assertNotIn("--min-files", stdout)
        self.assertNotIn("--include-nested", stdout)
        self.assertNotIn("--leaves-only", stdout)

    def test_version_matches_changelog(self) -> None:
        code, stdout, stderr = run_cli(["--version"])
        self.assertEqual(code, 0, stderr)
        self.assertIn(bulk_cbz.__version__, stdout)
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertIn(f"[{bulk_cbz.__version__}]", changelog)

    def test_no_convert_and_convert_to_are_exclusive(self) -> None:
        code, _stdout, stderr = run_cli([".", "--no-convert", "--convert-to", "jpeg"])
        self.assertEqual(code, 2)
        self.assertIn("use either --convert-to or --no-convert", stderr)

    def test_webp_converts_to_png_and_keeps_transparency(self) -> None:
        require_imagemagick()
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Ch"
            write_im_image(folder / "page.webp", "WEBP", transparent=True)
            write_file(folder / "keep.jpg", b"jpeg-bytes")
            write_file(folder / "keep.png", b"png-bytes")

            code, stdout, stderr = run_cli([str(root), "--verbose"])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(zip_names(root / "Ch.cbz"), ["keep.jpg", "keep.png", "page.png"])
            self.assertIn("page.webp -> page.png", stdout)
            self.assertEqual(zip_bytes(root / "Ch.cbz", "keep.jpg"), b"jpeg-bytes")
            self.assertEqual(zip_bytes(root / "Ch.cbz", "keep.png"), b"png-bytes")
            converted = zip_bytes(root / "Ch.cbz", "page.png")
            self.assertTrue(converted.startswith(PNG_SIGNATURE))
            self.assertEqual(png_color_type(converted), 6)

    def test_convert_to_jpeg_flattens_transparency(self) -> None:
        require_imagemagick()
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Ch"
            write_im_image(folder / "page.webp", "WEBP", transparent=True)
            write_file(folder / "keep.png", b"png-bytes")

            code, _stdout, stderr = run_cli([str(root), "--convert-to", "jpeg"])
            self.assertEqual(code, 0, stderr)
            self.assertEqual(zip_names(root / "Ch.cbz"), ["keep.png", "page.jpg"])
            self.assertEqual(zip_bytes(root / "Ch.cbz", "keep.png"), b"png-bytes")
            converted = zip_bytes(root / "Ch.cbz", "page.jpg")
            self.assertTrue(converted.startswith(JPEG_SOI))

    def test_dry_run_skips_conversion_when_imagemagick_missing(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Ch"
            write_file(folder / "page.webp")

            code, stdout, stderr = run_cli(
                [str(root), "--dry-run", "--verbose", "--imagemagick", "/missing/magick"]
            )
            self.assertEqual(code, 0)
            self.assertFalse((root / "Ch.cbz").exists())
            self.assertIn("ImageMagick", stderr)
            self.assertIn("without conversion", stderr)
            self.assertIn("page.webp", stdout)
            self.assertNotIn("page.webp -> page.png", stdout)

    def test_missing_imagemagick_warns_and_packs_originals(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_file(root / "Ch" / "page.webp", b"webp-bytes")
            code, _stdout, stderr = run_cli(
                [str(root), "--imagemagick", "/missing/magick"]
            )
            self.assertEqual(code, 0, stderr)
            self.assertIn("ImageMagick", stderr)
            self.assertIn("without conversion", stderr)
            self.assertEqual(zip_names(root / "Ch.cbz"), ["page.webp"])
            self.assertEqual(zip_bytes(root / "Ch.cbz", "page.webp"), b"webp-bytes")


if __name__ == "__main__":
    unittest.main()
