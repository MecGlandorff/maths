#!/usr/bin/env python3
"""Exercise the logistic-map CLI against independent mathematical properties."""

import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LogisticMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build = tempfile.TemporaryDirectory(prefix="maths-logistic-")
        cls.addClassCleanup(build.cleanup)
        cls.executable = Path(build.name) / "logistic_map"
        command = [
            *shlex.split(os.environ.get("CXX", "c++")),
            "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
            *shlex.split(os.environ.get("CPPFLAGS", "")),
            *shlex.split(os.environ.get("CXXFLAGS", "")),
            str(ROOT / "logistic_map.cpp"), "-o", str(cls.executable),
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

    def states(self, output):
        rows = re.findall(r"^\s+(\d+)\s+(\d+\.\d+)$", output, re.MULTILINE)
        self.assertEqual(len(rows), 8, output)
        indices = [int(index) for index, _ in rows]
        self.assertEqual(indices, list(range(indices[0], indices[0] + 8)))
        values = [float(value) for _, value in rows]
        self.assertTrue(all(math.isfinite(value) and 0 <= value <= 1 for value in values))
        return values

    def exponent(self, output):
        match = re.search(r"^Finite-time Lyapunov estimate: (\S+)", output, re.MULTILINE)
        self.assertIsNotNone(match, output)
        return float(match.group(1))

    def plot(self, output, width, height):
        rows = re.findall(r"^\d\.\d{2} \|([ *]+)\|$", output, re.MULTILINE)
        self.assertEqual(len(rows), height)
        self.assertTrue(all(len(row) == width for row in rows))
        self.assertTrue(all(any(row[column] == "*" for row in rows)
                            for column in range(width)))
        # At the left edge r=2.5, the attracting fixed point is exactly 0.6.
        occupied_left_rows = [index for index, row in enumerate(rows) if row[0] == "*"]
        self.assertEqual(occupied_left_rows, [round(0.4 * (height - 1))])

    def test_help_and_default_plot(self):
        help_output = self.run_cli("--help")
        self.assertIn("[r [samples [width [height]]]]", help_output)
        output = self.run_cli()
        self.assertIn("r = 3.9;", output)
        self.assertIn("retained states: 256", output)
        self.plot(output, 81, 25)
        self.states(output)

    def test_attracting_fixed_point_and_exact_local_multiplier(self):
        rate = 2.8
        output = self.run_cli(rate)
        for value in self.states(output):
            self.assertAlmostEqual(value, 1 - 1 / rate, delta=5e-12)
        # f'(1-1/r) = 2-r, so the fixed-point exponent is ln(|2-r|).
        self.assertAlmostEqual(self.exponent(output), math.log(abs(2 - rate)), delta=2e-9)

    def test_period_two_matches_closed_form(self):
        rate = 3.2
        output = self.run_cli("3.2e0", 512, 21, 11)
        values = self.states(output)
        discriminant = math.sqrt((rate - 3) * (rate + 1))
        expected = sorted(((rate + 1 - discriminant) / (2 * rate),
                           (rate + 1 + discriminant) / (2 * rate)))
        for observed, target in zip(sorted(values[:2]), expected):
            self.assertAlmostEqual(observed, target, delta=5e-12)
        for index in range(6):
            self.assertAlmostEqual(values[index], values[index + 2], delta=5e-12)
        self.assertLess(self.exponent(output), 0)

    def test_observed_period_four(self):
        output = self.run_cli(3.5, 256, 21, 11)
        values = self.states(output)
        for first, second in zip(values[:4], values[4:]):
            self.assertAlmostEqual(first, second, delta=5e-12)
        for first in range(4):
            for second in range(first + 1, 4):
                self.assertGreater(abs(values[first] - values[second]), 0.001)
        self.assertLess(self.exponent(output), 0)

    def test_sensitive_orbit_remains_bounded_and_obeys_recurrence(self):
        output = self.run_cli(3.9, 4096, 21, 11)
        values = self.states(output)
        for current, following in zip(values, values[1:]):
            self.assertAlmostEqual(following, 3.9 * current * (1 - current), delta=5e-12)
        # Allow numerical variation in chaotic trajectories across compilers.
        self.assertGreater(self.exponent(output), 0.3)
        self.assertLess(self.exponent(output), 0.7)

    def test_zero_derivative_is_reported(self):
        for rate, fixed_point in ((0, 0), (2, 0.5)):
            with self.subTest(rate=rate):
                output = self.run_cli(rate, 16, 21, 11)
                self.assertEqual(self.states(output), [fixed_point] * 8)
                self.assertEqual(self.exponent(output), -math.inf)
                self.assertIn("a sampled derivative is zero", output)

    def test_minimum_and_maximum_plot_sizes(self):
        minimum = self.run_cli(4, 16, 21, 11)
        self.plot(minimum, 21, 11)
        self.states(minimum)
        maximum = self.run_cli(4, 4096, 161, 61)
        self.plot(maximum, 161, 61)
        self.states(maximum)
        self.assertTrue(math.isfinite(self.exponent(maximum)))

    def test_rejects_malformed_and_nonfinite_rates(self):
        for rate in ("", "nan", "NaN", "inf", "-inf", "1e309", "3.9x",
                     " 3.9", "3.9 ", "0x1p1", "-0.01", "4.00001"):
            with self.subTest(rate=rate):
                self.run_cli(rate, expected_code=1)

    def test_rejects_invalid_integer_arguments_and_extra_arguments(self):
        invalid_arguments = [
            (3.9, 15), (3.9, 4097), (3.9, 16, 20), (3.9, 16, 162),
            (3.9, 16, 21, 10), (3.9, 16, 21, 62), (3.9, 16, 21, 11, 1),
        ]
        invalid_arguments.extend((3.9, value) for value in (
            "", "16.0", "16x", "-1", "999999999999999999999", " 16", "16 ",
        ))
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                self.run_cli(*arguments, expected_code=1)


if __name__ == "__main__":
    unittest.main()
