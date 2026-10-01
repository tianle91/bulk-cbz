#!/usr/bin/env python3
from __future__ import annotations

import io
import sys
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bulk_cbz  # noqa: E402


def write_file(path: Path, content: bytes = b"page") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def zip_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


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

            code, stdout, stderr = run_cli([str(series)])

            self.assertEqual(code, 0, stderr)
            self.assertTrue((series / "Vol 1.cbz").is_file())
            self.assertTrue((series / "Vol 2.cbz").is_file())
            self.assertTrue((series / "Vol 10.cbz").is_file())
            self.assertFalse((series / "library.cbz").exists())
            self.assertEqual(zip_names(series / "Vol 1.cbz"), ["1.jpg", "2.jpg", "10.jpg", "ComicInfo.xml"])
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

    def test_recursive_and_leaves_only(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            series = root / "series"
            write_file(series / "cover.jpg")
            write_file(series / "vol1" / "01.jpg")
            write_file(series / "vol2" / "01.jpg")

            run_cli([str(root), "--recursive"])
            self.assertTrue((root / "series.cbz").is_file())
            self.assertTrue((root / "series" / "vol1.cbz").is_file())
            self.assertTrue((root / "series" / "vol2.cbz").is_file())
            self.assertEqual(zip_names(root / "series.cbz"), ["cover.jpg"])

            (root / "series.cbz").unlink()
            (root / "series" / "vol1.cbz").unlink()
            (root / "series" / "vol2.cbz").unlink()

            run_cli([str(root), "--recursive", "--leaves-only"])
            self.assertFalse((root / "series.cbz").exists())
            self.assertTrue((root / "series" / "vol1.cbz").is_file())
            self.assertTrue((root / "series" / "vol2.cbz").is_file())

    def test_include_nested_packs_subfolder_pages(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            chapter = root / "Chapter 03"
            write_file(chapter / "pages" / "01.jpg")
            write_file(chapter / "pages" / "02.jpg")

            self.assertEqual(run_cli([str(root)])[0], 0)
            self.assertFalse((root / "Chapter 03.cbz").exists())

            self.assertEqual(run_cli([str(root), "--include-nested"])[0], 0)
            self.assertEqual(
                zip_names(root / "Chapter 03.cbz"),
                ["pages/01.jpg", "pages/02.jpg"],
            )

    def test_output_dir_min_files_exclude_and_hidden(self) -> None:
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
                    "--min-files",
                    "2",
                    "--exclude",
                    "*sample*",
                ]
            )
            self.assertEqual(code, 0, stderr)
            self.assertTrue((output / "Keep.cbz").is_file())
            self.assertFalse((output / "Thin.cbz").exists())
            self.assertFalse((output / "sample extras.cbz").exists())
            self.assertFalse((output / ".hidden.cbz").exists())
            self.assertFalse((output / "__MACOSX.cbz").exists())
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

    def test_extra_extension_and_compression(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            folder = root / "Custom"
            write_file(folder / "page.cbz.bin", b"not-a-cbz-but-custom")
            write_file(folder / "page.bin", b"hello-hello-hello-hello")

            code, _stdout, stderr = run_cli(
                [str(root), "--ext", "bin", "--compression", "deflate"]
            )
            self.assertEqual(code, 0, stderr)
            archive_path = root / "Custom.cbz"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, ["page.bin", "page.cbz.bin"])
                self.assertEqual(archive.getinfo("page.bin").compress_type, zipfile.ZIP_DEFLATED)

    def test_leaves_only_requires_recursive(self) -> None:
        code, _stdout, stderr = run_cli([".", "--leaves-only"])
        self.assertEqual(code, 2)
        self.assertIn("--leaves-only requires --recursive", stderr)

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


if __name__ == "__main__":
    unittest.main()
