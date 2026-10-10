#!/usr/bin/env python3
"""Check PCA through analytic spectra, exact moments, and geometric invariants."""

from fractions import Fraction
from functools import lru_cache
from itertools import product
import json
import math
import os
from pathlib import Path
import random
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KEYS = {
    "samples", "features", "components", "mean", "covariance", "eigenvalues",
    "singular_values", "axes", "explained_variance_ratio", "retained_variance_ratio",
    "scores", "reconstruction", "reconstruction_sse", "discarded_variance_sse",
}
ROTATION = ((1 / 3, 2 / 3, 2 / 3), (2 / 3, 1 / 3, -2 / 3),
            (2 / 3, -2 / 3, 1 / 3))
DEMO = tuple((10 + u + v, -3 + u - v, 5 + w)
             for u in (-4, 4) for v in (-1, 1) for w in (-0.25, 0.25))


def dot(left, right):
    return math.fsum(a * b for a, b in zip(left, right))


def serialize(rows):
    return f"{len(rows)} {len(rows[0])}\n" + "\n".join(
        " ".join(str(value) for value in row) for row in rows) + "\n"


def rotated_data(amplitudes=(6, 3, 0.75)):
    mean = (10, -3, 5)
    return tuple(tuple(mean[column] + math.fsum(
        sign * amplitude * axis[column]
        for sign, amplitude, axis in zip(signs, amplitudes, ROTATION))
        for column in range(3)) for signs in product((-1, 1), repeat=3))


@lru_cache(maxsize=None)
def exact_moments(rows):
    """Use rational arithmetic on the represented input values, not an eigensolver."""
    count, features = len(rows), len(rows[0])
    rational = [[Fraction(value) for value in row] for row in rows]
    mean = [sum(row[column] for row in rational) / count for column in range(features)]
    centered = [[value - mean[column] for column, value in enumerate(row)] for row in rational]
    covariance = [[float(sum(row[left] * row[right] for row in centered) / (count - 1))
                   for right in range(features)] for left in range(features)]
    return ([float(value) for value in mean], covariance,
            [[float(value) for value in row] for row in centered])


class PcaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-pca-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "pca"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "pca.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, input_text=None, expected_code=0):
        result = subprocess.run(
            [str(self.binary), *(str(argument) for argument in arguments)],
            input=input_text, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        if expected_code == 0:
            self.assertEqual(result.stderr, "")
        return result

    def close(self, actual, expected, scale=0, tolerance=2e-10):
        self.assertTrue(math.isfinite(actual), actual)
        allowed = tolerance * max(abs(expected), abs(scale))
        self.assertLessEqual(abs(actual - expected), allowed,
                             f"{actual!r} != {expected!r} (tolerance {allowed!r})")

    def matrix_close(self, actual, expected, scale=0, tolerance=2e-10):
        self.assertEqual(len(actual), len(expected))
        for actual_row, expected_row in zip(actual, expected):
            self.assertEqual(len(actual_row), len(expected_row))
            for actual_value, expected_value in zip(actual_row, expected_row):
                self.close(actual_value, expected_value, scale, tolerance)

    def assert_finite_json(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.assert_finite_json(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_finite_json(item)
        elif value is not None:
            self.assertIn(type(value), (int, float))
            self.assertTrue(math.isfinite(value), value)

    def validate(self, rows, components, output):
        data = json.loads(output)
        self.assertEqual(set(data), KEYS)
        self.assert_finite_json(data)
        samples, features = len(rows), len(rows[0])
        for key, expected in (("samples", samples), ("features", features),
                              ("components", components)):
            self.assertIs(type(data[key]), int)
            self.assertEqual(data[key], expected)
        mean, covariance, centered = exact_moments(tuple(map(tuple, rows)))
        spread = max(abs(value) for row in centered for value in row)
        covariance_scale = max(abs(value) for row in covariance for value in row)
        energy = math.fsum(value * value for row in centered for value in row)
        self.assertEqual(len(data["mean"]), features)
        for column in range(features):
            column_scale = max(abs(row[column]) for row in rows)
            self.close(data["mean"][column], mean[column], column_scale, 2e-12)
        self.matrix_close(data["covariance"], covariance, covariance_scale, 2e-12)

        values, axes = data["eigenvalues"], data["axes"]
        self.assertEqual(len(values), features)
        self.assertEqual(len(axes), features)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(all(value >= 0 for value in values))
        for axis in axes:
            self.assertEqual(len(axis), features)
            largest = max(range(features), key=lambda index: abs(axis[index]))
            self.assertGreaterEqual(axis[largest], -2e-14)
        for left in range(features):
            for right in range(features):
                self.close(dot(axes[left], axes[right]), int(left == right), 1, 2e-11)
            for column in range(features):
                self.close(dot(covariance[column], axes[left]),
                           values[left] * axes[left][column], covariance_scale, 2e-10)
        trace = math.fsum(covariance[index][index] for index in range(features))
        self.close(math.fsum(values), trace, covariance_scale)
        self.assertEqual(len(data["singular_values"]), features)
        for singular, value in zip(data["singular_values"], values):
            self.assertGreaterEqual(singular, 0)
            self.close(singular, math.sqrt((samples - 1) * value))

        ratios = data["explained_variance_ratio"]
        if trace == 0:
            self.assertIsNone(ratios)
            self.assertIsNone(data["retained_variance_ratio"])
        else:
            self.assertEqual(len(ratios), features)
            for ratio, value in zip(ratios, values):
                self.assertGreaterEqual(ratio, 0)
                self.close(ratio, value / trace, 1)
            self.close(math.fsum(ratios), 1)
            self.close(data["retained_variance_ratio"], math.fsum(ratios[:components]), 1)

        expected_scores = [[dot(row, axis) for axis in axes[:components]] for row in centered]
        self.matrix_close(data["scores"], expected_scores, spread)
        projected = [[math.fsum(score[axis] * axes[axis][column]
                                for axis in range(components))
                      for column in range(features)] for score in data["scores"]]
        reconstruction = [[mean[column] + row[column] for column in range(features)]
                          for row in projected]
        self.assertEqual(len(data["reconstruction"]), samples)
        for actual, expected in zip(data["reconstruction"], reconstruction):
            self.assertEqual(len(actual), features)
            for column in range(features):
                self.close(actual[column], expected[column], max(abs(mean[column]), spread))
        measured_sse = math.fsum((value - fitted) ** 2
                                 for row, fit in zip(centered, projected)
                                 for value, fitted in zip(row, fit))
        tail = (samples - 1) * math.fsum(values[components:])
        self.assertGreaterEqual(data["reconstruction_sse"], 0)
        self.assertGreaterEqual(data["discarded_variance_sse"], 0)
        self.close(data["reconstruction_sse"], measured_sse, energy)
        self.close(data["discarded_variance_sse"], tail, energy)
        self.close(data["reconstruction_sse"], tail, energy)
        if components == features:
            self.assertLessEqual(data["reconstruction_sse"], 2e-20 * energy)
        return data

    def pca(self, rows, components=None):
        if components is None:
            components = min(2, len(rows[0]))
        result = self.run_program("--input", "-", "--json", "--components", components,
                                  input_text=serialize(rows))
        return self.validate(rows, components, result.stdout)

    def check_projector(self, actual_axes, expected_axes):
        features = len(actual_axes[0])
        actual = [[math.fsum(axis[row] * axis[column] for axis in actual_axes)
                   for column in range(features)] for row in range(features)]
        expected = [[math.fsum(axis[row] * axis[column] for axis in expected_axes)
                     for column in range(features)] for row in range(features)]
        self.matrix_close(actual, expected, 1, 2e-10)

    def test_demo_for_every_component_count(self):
        expected_values = (256 / 7, 16 / 7, 0.5 / 7)
        for components, expected_sse in enumerate((272.5, 16.5, 0.5, 0)):
            with self.subTest(components=components):
                result = self.run_program("--json", "--components", components)
                data = self.validate(DEMO, components, result.stdout)
                for actual, expected in zip(data["eigenvalues"], expected_values):
                    self.close(actual, expected)
                self.close(data["reconstruction_sse"], expected_sse, 272.5)
        default = self.validate(DEMO, 2, self.run_program("--json").stdout)
        self.close(default["retained_variance_ratio"], 544 / 545)
        human = self.run_program()
        self.assertTrue(human.stdout.strip())
        self.assertFalse(human.stdout.lstrip().startswith("{"))

    def test_one_feature_and_closed_form_two_feature_spectrum(self):
        for components in (0, 1):
            data = self.pca(((-2,), (0,), (5,)), components)
            self.close(data["eigenvalues"][0], 13)
        rows = ((2, 4), (4, 1), (7, 3), (9, 8), (5, -2))
        covariance = exact_moments(rows)[1]
        a, b, c = covariance[0][0], covariance[0][1], covariance[1][1]
        gap = math.hypot(a - c, 2 * b)
        high, low = (a + c + gap) / 2, (a + c - gap) / 2
        for components in range(3):
            data = self.pca(rows, components)
            self.close(data["eigenvalues"][0], high)
            self.close(data["eigenvalues"][1], low)
            axis = data["axes"][0]
            for row in range(2):
                for column in range(2):
                    expected = (covariance[row][column] - low * int(row == column)) / gap
                    self.close(axis[row] * axis[column], expected, 1)

    def test_rotated_spectrum_and_repeated_eigenspaces(self):
        rows = rotated_data()
        for components in range(4):
            data = self.pca(rows, components)
            for index, expected in enumerate((288 / 7, 72 / 7, 4.5 / 7)):
                self.close(data["eigenvalues"][index], expected)
                self.check_projector([data["axes"][index]], [ROTATION[index]])
        repeated = rotated_data((3, 3, 1.5))
        for components in range(4):
            data = self.pca(repeated, components)
            for actual, expected in zip(data["eigenvalues"], (72 / 7, 72 / 7, 18 / 7)):
                self.close(actual, expected)
            self.check_projector(data["axes"][:2], ROTATION[:2])
        isotropic = tuple(tuple(sign * int(column == axis) for column in range(3))
                          for axis in range(3) for sign in (-1, 1))
        for components in range(4):
            data = self.pca(isotropic, components)
            self.close(data["reconstruction_sse"], 2 * (3 - components), 6)

    def test_constant_and_rank_deficient_inputs(self):
        for row in ((0,), (0.1, -3, 2), (1e100, -1e-100, 0)):
            for components in (0, len(row)):
                data = self.pca((row,) * 7, components)
                self.assertEqual(data["eigenvalues"], [0] * len(row))
                self.assertEqual(data["reconstruction_sse"], 0)
                self.assertEqual(data["reconstruction"], [list(row)] * 7)
        rows = tuple(tuple(offset + t * direction for offset, direction in
                           zip((10, 20, -5, 2), (2, -1, 0, 5))) for t in (-3, -1, 1, 3))
        for components in (0, 1, 2, 4):
            data = self.pca(rows, components)
            self.close(data["eigenvalues"][0], 200)
            if components:
                self.assertLessEqual(data["reconstruction_sse"], 1e-20 * 600)
        wide = (tuple(-value for value in range(1, 9)), tuple(range(1, 9)))
        for components in (0, 1, 8):
            data = self.pca(wide, components)
            self.close(data["eigenvalues"][0], 408)

    def test_full_256_by_8_shape_with_known_spectrum(self):
        hadamard = tuple(tuple(-1 if bin(row & column).count("1") % 2 else 1
                               for column in range(8)) for row in range(8))
        rows = tuple(tuple(sum((1 if mask & (1 << axis) else -1) * (axis + 1)
                               * hadamard[axis][column] for axis in range(8))
                           for column in range(8)) for mask in range(256))
        for components in (3, 8):
            data = self.pca(rows, components)
            for index, amplitude in enumerate(range(8, 0, -1)):
                self.close(data["eigenvalues"][index], 8 * 256 * amplitude ** 2 / 255)
                axis = [value / math.sqrt(8) for value in hadamard[amplitude - 1]]
                self.check_projector([data["axes"][index]], [axis])
            if components == 3:
                self.close(data["reconstruction_sse"], 8 * 256 * 55)
                self.close(data["retained_variance_ratio"], 149 / 204)

    def test_scaling_translation_and_sample_permutation(self):
        rows = rotated_data()
        baseline = self.pca(rows, 2)
        for factor in (1e-90, 1e90, -3, 2 ** -20, 2 ** 20):
            with self.subTest(factor=factor):
                scaled = tuple(tuple(factor * value for value in row) for row in rows)
                data = self.pca(scaled, 2)
                for index in range(3):
                    self.close(data["eigenvalues"][index], factor ** 2 * baseline["eigenvalues"][index])
                    self.check_projector([data["axes"][index]], [baseline["axes"][index]])
                self.close(data["reconstruction_sse"], factor ** 2 * baseline["reconstruction_sse"])
                self.close(data["retained_variance_ratio"], baseline["retained_variance_ratio"])
                expected = [[factor * value for value in row] for row in baseline["reconstruction"]]
                self.matrix_close(data["reconstruction"], expected, abs(factor) * 20)
                for index in range(2):
                    sign = 1 if dot(data["axes"][index], baseline["axes"][index]) > 0 else -1
                    for actual, reference in zip(data["scores"], baseline["scores"]):
                        self.close(actual[index], factor * sign * reference[index], abs(factor) * 10)
        for offset in ((100, -50, 20), (2 ** 40, -(2 ** 42), 2 ** 38)):
            translated = tuple(tuple(value + shift for value, shift in zip(row, offset)) for row in rows)
            data = self.pca(translated, 2)
            self.matrix_close(data["covariance"], baseline["covariance"], 50)
            self.close(data["reconstruction_sse"], baseline["reconstruction_sse"])
        order = (6, 0, 3, 7, 2, 5, 1, 4)
        data = self.pca(tuple(rows[index] for index in order), 2)
        self.matrix_close(data["covariance"], baseline["covariance"], 50)
        self.matrix_close(data["reconstruction"], [baseline["reconstruction"][index] for index in order], 20)

    def test_feature_permutation_and_repeated_observations(self):
        rows = rotated_data()
        baseline = self.pca(rows, 2)
        order = (2, 0, 1)
        data = self.pca(tuple(tuple(row[index] for index in order) for row in rows), 2)
        expected = [[row[index] for index in order] for row in baseline["reconstruction"]]
        self.matrix_close(data["reconstruction"], expected, 20)
        for index in range(3):
            axis = [baseline["axes"][index][column] for column in order]
            self.check_projector([data["axes"][index]], [axis])
        repeated = self.pca(rows + rows, 2)
        for original, duplicate in zip(baseline["eigenvalues"], repeated["eigenvalues"]):
            self.close(duplicate, original * 2 * 7 / 15)
        self.close(repeated["reconstruction_sse"], 2 * baseline["reconstruction_sse"])

    def test_seeded_multidimensional_invariants(self):
        rng = random.Random(20261010)
        for features in (2, 4, 6, 8):
            rows = tuple(tuple(rng.randrange(-9, 10) for _ in range(features)) for _ in range(19))
            for components in (0, features // 2, features):
                with self.subTest(features=features, components=components):
                    self.pca(rows, components)

    def test_numeric_bounds_decimal_syntax_and_file_input(self):
        for magnitude in (1e-100, 1e100):
            self.pca(((-magnitude,), (magnitude,)), 0)
            self.pca(((-magnitude,), (magnitude,)), 1)
        text = "  2\t3\n+.5 1. -0\n -5e-1 +1E0 -0.0e100  \n"
        rows = ((0.5, 1, 0), (-0.5, 1, 0))
        data_file = self.directory / "observations with spaces.txt"
        data_file.write_text(text, encoding="utf-8")
        for arguments in (("--input", "-", "--json"),
                          ("--json", "--input", str(data_file)),
                          ("--components", 2, "--input", str(data_file), "--json")):
            result = self.run_program(*arguments, input_text=text)
            self.validate(rows, 2, result.stdout)
        help_result = self.run_program("--help")
        for flag in ("--input", "--components", "--json"):
            self.assertIn(flag, help_result.stdout)

    def test_human_output_limits_the_preview_to_eight_samples(self):
        rows = tuple((value,) for value in range(11))
        result = self.run_program("--input", "-", input_text=serialize(rows))
        preview = [line for line in result.stdout.splitlines()
                   if line.startswith("[") and " -> " in line]
        self.assertEqual(len(preview), 8)
        for index, line in enumerate(preview):
            scores, reconstruction = (json.loads(part) for part in line.split(" -> "))
            self.assertEqual(scores, [index - 5])
            self.assertEqual(reconstruction, [index])
        self.assertIn("3 more samples", result.stdout)

    def test_invalid_flags_and_input(self):
        invalid_flags = [
            ("--unknown",), ("extra",), ("--input",), ("--components",),
            ("--help", "--json"), ("--json", "--help"), ("--help", "--help"),
            ("--json", "--json"), ("--components", 1, "--components", 2),
            ("--input", "-", "--input", "-"), ("--components", 4),
            ("--input", ""), ("--input", str(self.directory / "does-not-exist")),
        ]
        invalid_flags.extend(("--components", value) for value in
                             ("", "-1", "+1", "1.0", "1x", " 1", "1 ", "999999999999999999999"))
        for arguments in invalid_flags:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, input_text=serialize(DEMO), expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
        invalid_inputs = [
            "", "2", "0 1", "1 1 0", "257 1", "2 0", "2 9", "-2 1 0 0",
            "+2 1 0 0", "2 -1 0 0", "2 +1 0 0", "2.0 1 0 0", "2 1x 0 0",
            "999999999999999999999 1", "2 2 1 2 3", "2 1 1 2 3", "2 1 1 2 extra",
        ]
        invalid_tokens = (
            "nan", "NaN", "nan(0)", "+nan", "inf", "+inf", "-inf", "Infinity",
            "0x1p0", "0X1.0P+2", "1_000", "1,5", "--1", "+", "-", ".",
            "1e", "1e+", "1e-", "1e1x", "1.2.3", "1e309", "-1e309",
            "1e-999", "1e-101", "9e-101", "1.0001e100", "-1.0001e100",
        )
        invalid_inputs.extend(f"2 1 1 {token}" for token in invalid_tokens)
        for text in invalid_inputs:
            with self.subTest(input_text=text):
                result = self.run_program("--input", "-", "--json", input_text=text, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
        result = self.run_program("--input", "-", "--components", 2, "--json",
                                  input_text="2 1 1 2", expected_code=1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
