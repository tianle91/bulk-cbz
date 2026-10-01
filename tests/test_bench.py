#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "bench.py"


class BenchTests(unittest.TestCase):
    def test_quick_benchmark_runs(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(BENCH), "--quick", "--jobs", "2"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("discover_folders", proc.stdout)
        self.assertIn("plan_conversions", proc.stdout)
        self.assertIn("pack jpeg --jobs 1", proc.stdout)
        self.assertIn("pack jpeg --jobs 2", proc.stdout)
        self.assertIn("os.walk listing", proc.stdout)
        self.assertIn("os.scandir listing", proc.stdout)
        self.assertRegex(proc.stdout, r"ch/s|file/s")
        self.assertIn("cli discover=", proc.stdout)
        self.assertNotIn("convert webp --jobs 1", proc.stdout)

    def test_repeat_reports_mean_and_stdev(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(BENCH), "--quick", "--jobs", "1", "--repeat", "2", "--no-listing"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("repeat=2", proc.stdout)
        self.assertIn("±", proc.stdout)

    def test_jobs_must_be_positive(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(BENCH), "--quick", "--jobs", "0"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--jobs must be at least 1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
