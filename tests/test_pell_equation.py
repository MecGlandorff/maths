#!/usr/bin/env python3
"""Compile the Pell explorer and check its public CLI with exact integer oracles."""

from fractions import Fraction
from math import isqrt
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([+-]\d+)\s+(above|below)$", re.M)
SOLUTION = re.compile(r"Smallest positive solution: x = (\d+), y = (\d+)")
EXPANSION = re.compile(r"sqrt\((\d+)\) = \[(\d+); \(([\d, ]+)\)\]")


def coefficients_from_bounds(value, count=64):
    """Extract coefficients from rational intervals, without the C++ recurrence."""
    scale = 10**200
    floor = isqrt(value * scale * scale)
    lower = Fraction(floor, scale)
    upper = Fraction(floor + 1, scale)
    coefficients = []
    for _ in range(count):
        coefficient = lower.numerator // lower.denominator
        if coefficient != upper.numerator // upper.denominator:
            raise AssertionError("Reference interval no longer determines a coefficient")
        coefficients.append(coefficient)
        lower, upper = 1 / (upper - coefficient), 1 / (lower - coefficient)
    return coefficients


def reference_rows(value, coefficients):
    rows = []
    for index, coefficient in enumerate(coefficients):
        # Rebuild each finite fraction backwards instead of sharing the C++
        # numerator/denominator recurrence. Python integers have no 64-bit limit.
        fraction = Fraction(coefficient)
        for earlier in reversed(coefficients[:index]):
            fraction = earlier + 1 / fraction
        numerator, denominator = fraction.numerator, fraction.denominator
        residual = numerator * numerator - value * denominator * denominator
        rows.append((index, coefficient, numerator, denominator, residual,
                     "above" if residual > 0 else "below"))
        if residual == 1:
            return rows
    raise AssertionError("Reference did not reach a positive Pell solution")


class PellEquationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="maths-pell-")
        cls.addClassCleanup(directory.cleanup)
        cls.binary = Path(directory.name) / "pell_equation"
        compiler = shlex.split(os.environ.get("CXX", "c++"))
        flags = shlex.split(os.environ.get("CXXFLAGS", ""))
        subprocess.run(
            compiler + ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic",
                        "-Wconversion", "-Wsign-conversion", "-Werror"]
            + flags + [str(ROOT / "pell_equation.cpp"), "-o", str(cls.binary)],
            check=True,
        )

    def run_program(self, *arguments):
        return subprocess.run([str(self.binary), *map(str, arguments)],
                              capture_output=True, text=True, timeout=5)

    def solution(self, output):
        match = SOLUTION.search(output)
        self.assertIsNotNone(match, output)
        return tuple(map(int, match.groups()))

    def test_default_and_help(self):
        default = self.run_program()
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stderr, "")
        self.assertEqual(default.stdout, self.run_program(13).stdout)
        self.assertEqual(self.solution(default.stdout), (649, 180))
        help_result = self.run_program("--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("Usage:", help_result.stdout)
        self.assertEqual(help_result.stderr, "")

    def test_known_large_solutions(self):
        for value, expected in {61: (1766319049, 226153980),
                                97: (62809633, 6377352)}.items():
            with self.subTest(value=value):
                result = self.run_program(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.solution(result.stdout), expected)
                self.assertEqual(expected[0] ** 2 - value * expected[1] ** 2, 1)

    def test_all_nonsquares_against_exact_interval_oracle(self):
        for value in range(2, 101):
            if isqrt(value) ** 2 == value:
                continue
            with self.subTest(value=value):
                result = self.run_program(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                coefficients = coefficients_from_bounds(value)
                expected = reference_rows(value, coefficients)
                actual = [tuple(map(int, row[:5])) + (row[5],)
                          for row in ROW.findall(result.stdout)]
                self.assertEqual(actual, expected)
                self.assertEqual(self.solution(result.stdout), expected[-1][2:4])

                expansion = EXPANSION.search(result.stdout)
                self.assertIsNotNone(expansion, result.stdout)
                self.assertEqual(tuple(map(int, expansion.groups()[:2])),
                                 (value, isqrt(value)))
                period = list(map(int, expansion.group(3).split(", ")))
                length = coefficients[1:].index(2 * isqrt(value)) + 1
                self.assertEqual(len(period), length)
                self.assertEqual(period * 2, coefficients[1:2 * length + 1])
                self.assertEqual(len(actual), length if length % 2 == 0 else 2 * length)

    def test_small_solutions_are_minimal_by_brute_force(self):
        for value in range(2, 31):
            if isqrt(value) ** 2 == value:
                continue
            with self.subTest(value=value):
                # This search uses no continued-fraction identities.
                for denominator in range(1, 10000):
                    square = 1 + value * denominator * denominator
                    numerator = isqrt(square)
                    if numerator * numerator == square:
                        break
                else:
                    self.fail("Brute-force reference bound was too small")
                result = self.run_program(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.solution(result.stdout), (numerator, denominator))

    def test_invalid_inputs(self):
        invalid = [("",), ("0",), ("1",), ("-2",), ("+2",), ("2.0",),
                   ("2junk",), (" 2",), ("2 ",), ("101",),
                   ("18446744073709551616",), ("--unknown",),
                   ("2", "3"), ("--help", "2")]
        invalid.extend((str(root * root),) for root in range(2, 11))
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
