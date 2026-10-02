#!/usr/bin/env python3
"""Check the sandpile's public CLI with a different legal toppling order."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def reference_stabilization(size, grains):
    """Sweep backwards, toppling each unstable cell just once per sweep."""
    heights = [[0] * size for _ in range(size)]
    odometer = [[0] * size for _ in range(size)]
    heights[size // 2][size // 2] = grains
    while True:
        changed = False
        for row in range(size - 1, -1, -1):
            for column in range(size - 1, -1, -1):
                if heights[row][column] < 4:
                    continue
                changed = True
                heights[row][column] -= 4
                odometer[row][column] += 1
                if row > 0:
                    heights[row - 1][column] += 1
                if row + 1 < size:
                    heights[row + 1][column] += 1
                if column > 0:
                    heights[row][column - 1] += 1
                if column + 1 < size:
                    heights[row][column + 1] += 1
        if not changed:
            return heights, odometer


class AbelianSandpileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = tempfile.TemporaryDirectory(prefix="maths-sandpile-")
        cls.addClassCleanup(build.cleanup)
        cls.executable = Path(build.name) / "abelian_sandpile"
        command = [
            *shlex.split(os.environ.get("CXX", "c++")),
            "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            *shlex.split(os.environ.get("CPPFLAGS", "")),
            *shlex.split(os.environ.get("CXXFLAGS", "")),
            str(ROOT / "abelian_sandpile.cpp"), "-o", str(cls.executable),
        ]
        subprocess.run(command, check=True, timeout=60)

    def run_cli(self, *arguments, expected_code=0):
        result = subprocess.run(
            [str(self.executable), *map(str, arguments)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_code, result.stderr)
        if expected_code == 0:
            self.assertEqual(result.stderr, "")
        else:
            self.assertEqual(result.stdout, "")
            self.assertIn("Invalid arguments.", result.stderr)
            self.assertIn("Usage:", result.stderr)
        return result.stdout

    def report(self, output, size, with_odometer=True):
        self.assertIn(f"Abelian sandpile: {size} x {size};", output)
        heights = re.findall(r"^\|([0-3]+)\|$", output, re.MULTILINE)
        self.assertEqual(len(heights), size)
        self.assertTrue(all(len(row) == size for row in heights))
        activity = re.findall(r"^\|([ .:\-=+*#%@]+)\|$", output, re.MULTILINE)
        self.assertEqual(len(activity), size)
        self.assertTrue(all(len(row) == size for row in activity))
        result = {
            "heights": [[int(value) for value in row] for row in heights],
            "activity": activity,
        }
        labels = {
            "initial": "Initial grains", "retained": "Retained grains",
            "lost": "Lost grains", "topplings": "Total topplings",
            "maximum": "Maximum topplings at one cell",
        }
        for key, label in labels.items():
            matches = re.findall(rf"^{label}: (\d+)$", output, re.MULTILINE)
            self.assertEqual(len(matches), 1, label)
            result[key] = int(matches[0])
        if with_odometer:
            self.assertIn("row column topplings\n", output)
            records = output.split("row column topplings\n", 1)[1].splitlines()
            self.assertEqual(len(records), size * size)
            odometer = [[None] * size for _ in range(size)]
            for record in records:
                self.assertRegex(record, r"^\d+ \d+ \d+$")
                row, column, count = map(int, record.split())
                self.assertTrue(0 <= row < size and 0 <= column < size)
                self.assertIsNone(odometer[row][column], "duplicate odometer coordinate")
                odometer[row][column] = count
            result["odometer"] = odometer
        else:
            self.assertNotIn("Exact odometer", output)
        return result

    def verify_balance_and_symmetry(self, report, size, grains):
        heights = report["heights"]
        odometer = report["odometer"]
        self.assertEqual(report["initial"], grains)
        self.assertEqual(report["retained"], sum(map(sum, heights)))
        self.assertEqual(report["retained"] + report["lost"], grains)
        self.assertEqual(report["topplings"], sum(map(sum, odometer)))
        self.assertEqual(report["maximum"], max(map(max, odometer)))
        self.assertLessEqual(report["topplings"], grains * (size + 1) ** 2 // 8)
        boundary_loss = 0
        for row in range(size):
            for column in range(size):
                neighbors = [(row - 1, column), (row + 1, column),
                             (row, column - 1), (row, column + 1)]
                inside = [(r, c) for r, c in neighbors if 0 <= r < size and 0 <= c < size]
                initial_height = grains if row == column == size // 2 else 0
                expected_height = (initial_height - 4 * odometer[row][column]
                                   + sum(odometer[r][c] for r, c in inside))
                self.assertEqual(heights[row][column], expected_height)
                boundary_loss += (4 - len(inside)) * odometer[row][column]
                self.assertEqual(report["activity"][row][column] == " ",
                                 odometer[row][column] == 0)
        self.assertEqual(report["lost"], boundary_loss)
        for matrix in (heights, odometer):
            self.assertEqual(matrix, matrix[::-1])
            self.assertEqual(matrix, [row[::-1] for row in matrix])
            self.assertEqual(matrix, list(map(list, zip(*matrix))))

    def test_help_and_default_visualization(self):
        help_output = self.run_cli("--help")
        self.assertIn("[size [grains]] [--odometer]", help_output)
        self.assertIn("odd, 3..61", help_output)
        report = self.report(self.run_cli(), 31, with_odometer=False)
        self.assertEqual(report["initial"], 10000)
        self.assertEqual(report["retained"], sum(map(sum, report["heights"])))
        self.assertEqual(report["retained"] + report["lost"], 10000)

    def test_already_stable_piles(self):
        for grains in range(4):
            with self.subTest(grains=grains):
                report = self.report(self.run_cli(3, grains, "--odometer"), 3)
                self.assertEqual(report["heights"], [[0, 0, 0], [0, grains, 0], [0, 0, 0]])
                self.assertEqual(report["topplings"], 0)
                self.assertEqual(report["lost"], 0)
                self.verify_balance_and_symmetry(report, 3, grains)

    def test_one_toppling_is_an_orthogonal_cross(self):
        report = self.report(self.run_cli(3, 4, "--odometer"), 3)
        self.assertEqual(report["heights"], [[0, 1, 0], [1, 0, 1], [0, 1, 0]])
        self.assertEqual(report["odometer"], [[0, 0, 0], [0, 1, 0], [0, 0, 0]])
        self.assertEqual(report["activity"], ["   ", " @ ", "   "])
        self.assertEqual(report["lost"], 0)
        self.verify_balance_and_symmetry(report, 3, 4)

    def test_exact_boundary_loss_example(self):
        report = self.report(self.run_cli(3, 16, "--odometer"), 3)
        self.assertEqual(report["heights"], [[2, 1, 2], [1, 0, 1], [2, 1, 2]])
        self.assertEqual(report["odometer"], [[0, 1, 0], [1, 5, 1], [0, 1, 0]])
        self.assertEqual(report["activity"], [" = ", "=@=", " = "])
        self.assertEqual((report["retained"], report["lost"], report["topplings"]), (12, 4, 9))
        self.verify_balance_and_symmetry(report, 3, 16)

    def test_different_legal_toppling_order_agrees(self):
        for size, grains in ((3, 41), (3, 100), (5, 31), (5, 200), (7, 400), (9, 1000)):
            with self.subTest(size=size, grains=grains):
                report = self.report(self.run_cli(size, grains, "--odometer"), size)
                heights, odometer = reference_stabilization(size, grains)
                self.assertEqual(report["heights"], heights)
                self.assertEqual(report["odometer"], odometer)
                self.verify_balance_and_symmetry(report, size, grains)

    def test_odometer_flag_positions(self):
        trailing = self.run_cli(3, 16, "--odometer")
        self.assertEqual(self.run_cli("--odometer", 3, 16), trailing)
        self.assertEqual(self.run_cli(3, "--odometer", 16), trailing)

    def test_maximum_inputs_and_empty_maximum_grid(self):
        # run_cli's timeout also guards practical runtime at the supported limits.
        for size, grains in ((61, 0), (3, 100000), (61, 100000)):
            with self.subTest(size=size, grains=grains):
                report = self.report(self.run_cli(size, grains, "--odometer"), size)
                self.verify_balance_and_symmetry(report, size, grains)

    def test_invalid_size_and_grain_arguments(self):
        sizes = ("", 0, 1, 2, 4, 60, 62, 63, -3, "3.0", "+3", " 3", "3 ",
                 "3x", "nan", "inf", "1e1", "18446744073709551616")
        grains = ("", -1, 100001, "4.0", "+4", " 4", "4 ", "4x", "nan", "inf",
                  "1e3", "18446744073709551616")
        for size in sizes:
            with self.subTest(size=size):
                self.run_cli(size, expected_code=1)
        for count in grains:
            with self.subTest(grains=count):
                self.run_cli(3, count, expected_code=1)

    def test_unknown_repeated_and_extra_arguments(self):
        for arguments in ((3, 4, 5), ("--unknown",), ("--help", 3),
                          ("--odometer", "--odometer"), (3, 4, "--odometer", "--odometer")):
            with self.subTest(arguments=arguments):
                self.run_cli(*arguments, expected_code=1)


if __name__ == "__main__":
    unittest.main()
