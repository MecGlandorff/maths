#!/usr/bin/env python3
"""Check ridge fits through the public CLI with exact, independent oracles."""

from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAMBDAS = (0, 0.01, 0.1, 1, 10)
T = (-2, -1, 0, 1, 2)
Q = (1, -2, 2, -2, 1)
PRESETS = {
    "near-collinear": tuple((t, t + 0.01 * q, 1 + 3 * t + 0.1 * q) for t, q in zip(T, Q)),
    "collinear": tuple((t, t, 1 + 3 * t) for t in T),
    "orthogonal": tuple((t, q, 1 + 3 * t - 2 * q) for t, q in zip(T, Q)),
}
KEYS = {
    "samples", "feature_means", "target_mean", "covariance", "eigenvalues",
    "eigenvectors", "rank", "rank_threshold", "condition_number", "fits",
}
FIT_KEYS = {
    "lambda", "bias", "weights", "data_loss", "penalty", "objective",
    "weight_norm", "shrinkage", "effective_df", "regularized_condition",
    "predictions", "residuals",
}


def rational(value):
    """The oracle operates on the exact binary doubles accepted by the CLI."""
    return Fraction(float(value))


def serialize(rows):
    return str(len(rows)) + "\n" + "\n".join(" ".join(map(str, row)) for row in rows) + "\n"


def moments(rows):
    data = [tuple(map(rational, row)) for row in rows]
    means = tuple(sum(row[j] for row in data) / len(data) for j in range(3))
    centered = [tuple(row[j] - means[j] for j in range(3)) for row in data]
    a = sum(x * x for x, _, _ in centered) / len(data)
    b = sum(z * z for _, z, _ in centered) / len(data)
    c = sum(x * z for x, z, _ in centered) / len(data)
    g = (sum(x * y for x, _, y in centered) / len(data),
         sum(z * y for _, z, y in centered) / len(data))
    return means, (a, b, c), g, centered


def as_decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


def spectrum(rows):
    _, (a, b, c), _, _ = moments(rows)
    with localcontext() as context:
        context.prec = 100
        largest = (as_decimal(a + b) +
                   (as_decimal(a - b) ** 2 + 4 * as_decimal(c) ** 2).sqrt()) / 2
        smallest = as_decimal(a * b - c * c) / largest if largest else Decimal(0)
        return largest, smallest


def numerical_rank(rows):
    eigenvalues = spectrum(rows)
    threshold = 64 * sys.float_info.epsilon * float(eigenvalues[0])
    return sum(value > Decimal(threshold) for value in eigenvalues)


def fit_oracle(rows, strength):
    means, (a, b, c), g, centered = moments(rows)
    strength = rational(strength)
    rank = numerical_rank(rows)
    if strength or rank == 2:
        determinant = (a + strength) * (b + strength) - c * c
        weights = (((b + strength) * g[0] - c * g[1]) / determinant,
                   ((a + strength) * g[1] - c * g[0]) / determinant)
    elif rank == 0:
        weights = (Fraction(0), Fraction(0))
    elif a * b == c * c:
        # For a rank-one symmetric H, H^+ = H / trace(H)^2.
        weights = ((a * g[0] + c * g[1]) / (a + b) ** 2,
                   (c * g[0] + b * g[1]) / (a + b) ** 2)
    else:
        # Truncated projector P_max=(H-lambda_min I)/(lambda_max-lambda_min).
        with localcontext() as context:
            context.prec = 100
            maximum, minimum = spectrum(rows)
            divisor = maximum * (maximum - minimum)
            weights = tuple(Fraction(value) for value in (
                ((as_decimal(a) - minimum) * as_decimal(g[0]) +
                 as_decimal(c) * as_decimal(g[1])) / divisor,
                (as_decimal(c) * as_decimal(g[0]) +
                 (as_decimal(b) - minimum) * as_decimal(g[1])) / divisor,
            ))
    bias = means[2] - weights[0] * means[0] - weights[1] * means[1]
    predictions = [means[2] + weights[0] * x + weights[1] * z for x, z, _ in centered]
    residuals = [weights[0] * x + weights[1] * z - y for x, z, y in centered]
    loss = sum(value * value for value in residuals) / (2 * len(rows))
    penalty = strength * sum(value * value for value in weights) / 2
    return bias, weights, predictions, residuals, loss, penalty


class RidgeRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-ridge-regression-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "ridge_regression"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "ridge_regression.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, input_text=None, expected_code=0):
        result = subprocess.run([str(self.binary), *map(str, arguments)], input=input_text,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        if expected_code == 0:
            self.assertEqual(result.stderr, "")
        return result

    def close(self, actual, expected, scale=0, tolerance=5e-10):
        expected = float(expected)
        self.assertTrue(math.isfinite(actual), actual)
        bound = tolerance * max(abs(expected), abs(scale))
        self.assertLessEqual(abs(actual - expected), bound,
                             f"{actual!r} != {expected!r}; tolerance={bound!r}")

    def finite(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.finite(item)
        elif isinstance(value, list):
            for item in value:
                self.finite(item)
        elif value is not None:
            self.assertIn(type(value), (int, float))
            self.assertTrue(math.isfinite(value), value)

    def validate(self, rows, output, strengths=DEFAULT_LAMBDAS):
        data = json.loads(output)
        self.assertEqual(set(data), KEYS)
        self.finite(data)
        self.assertIs(type(data["samples"]), int)
        self.assertEqual(data["samples"], len(rows))
        means, (a, b, c), _, _ = moments(rows)
        self.assertEqual(len(data["feature_means"]), 2)
        for actual, expected in zip(data["feature_means"], means[:2]):
            self.close(actual, expected, 1e-12, tolerance=4e-13)
        self.close(data["target_mean"], means[2], 1e-12, tolerance=4e-13)
        self.assertEqual(len(data["covariance"]), 2)
        for actual, expected in zip(data["covariance"], ((a, c), (c, b))):
            self.assertEqual(len(actual), 2)
            for value, exact in zip(actual, expected):
                self.close(value, exact, math.sqrt(float(a * b)) * 1e-12, tolerance=4e-12)
        maximum, minimum = map(float, spectrum(rows))
        self.assertEqual(len(data["eigenvalues"]), 2)
        self.close(data["eigenvalues"][0], maximum, tolerance=4e-12)
        self.close(data["eigenvalues"][1], minimum, maximum * 1e-16, tolerance=4e-12)
        self.assertGreaterEqual(data["eigenvalues"][1], 0)
        threshold = 64 * sys.float_info.epsilon * maximum
        self.close(data["rank_threshold"], threshold, tolerance=4e-12)
        rank = numerical_rank(rows)
        self.assertIs(type(data["rank"]), int)
        self.assertEqual(data["rank"], rank)
        if rank < 2:
            self.assertIsNone(data["condition_number"])
        else:
            self.close(data["condition_number"], maximum / minimum, tolerance=1e-10)
        vectors = data["eigenvectors"]
        self.assertEqual(len(vectors), 2)
        for vector, eigenvalue in zip(vectors, (maximum, minimum)):
            self.assertEqual(len(vector), 2)
            self.close(sum(x * x for x in vector), 1, tolerance=4e-13)
            for i in range(2):
                product = sum(float(entry) * value for entry, value in
                              zip(((a, c), (c, b))[i], vector))
                self.close(product, eigenvalue * vector[i], maximum, tolerance=4e-12)
        self.close(sum(x * y for x, y in zip(*vectors)), 0, 1, tolerance=4e-13)
        self.assertEqual(len(data["fits"]), len(strengths))
        target_scale = max(abs(float(row[2])) for row in rows)
        energy = sum(float(row[2]) ** 2 for row in rows) / (2 * len(rows))
        for fit, strength in zip(data["fits"], strengths):
            self.assertEqual(set(fit), FIT_KEYS)
            self.close(fit["lambda"], rational(strength), tolerance=0)
            bias, weights, predictions, residuals, loss, penalty = fit_oracle(rows, strength)
            self.close(fit["bias"], bias, target_scale)
            self.assertEqual(len(fit["weights"]), 2)
            for actual, expected in zip(fit["weights"], weights):
                self.close(actual, expected, 1)
            self.close(fit["weight_norm"], math.hypot(*map(float, weights)), 1e-12)
            self.close(fit["data_loss"], loss, energy * 1e-12)
            self.close(fit["penalty"], penalty, energy * 1e-12)
            self.close(fit["objective"], loss + penalty, energy * 1e-12)
            self.assertGreaterEqual(fit["data_loss"], 0)
            self.assertGreaterEqual(fit["penalty"], 0)
            for label, expected in (("predictions", predictions), ("residuals", residuals)):
                self.assertEqual(len(fit[label]), len(rows))
                for actual, exact in zip(fit[label], expected):
                    self.close(actual, exact, target_scale)
            strength = float(strength)
            factors = [value / (value + strength) if strength else int(value > threshold)
                       for value in (maximum, minimum)]
            self.assertEqual(len(fit["shrinkage"]), 2)
            for actual, expected in zip(fit["shrinkage"], factors):
                self.close(actual, expected, tolerance=1e-10)
                self.assertGreaterEqual(actual, 0)
                self.assertLessEqual(actual, 1)
            self.close(fit["effective_df"], 1 + sum(factors), tolerance=1e-11)
            if strength or rank == 2:
                self.close(fit["regularized_condition"], (maximum + strength) / (minimum + strength),
                           tolerance=1e-10)
            else:
                self.assertIsNone(fit["regularized_condition"])
        return data

    def explore(self, rows, strengths=DEFAULT_LAMBDAS):
        result = self.run_program("--input", "-", "--lambdas", ",".join(map(str, strengths)),
                                  "--json", input_text=serialize(rows))
        return self.validate(rows, result.stdout, strengths)

    def test_presets_and_default(self):
        for name, rows in PRESETS.items():
            with self.subTest(example=name):
                self.validate(rows, self.run_program("--example", name, "--json").stdout)
        data = self.validate(PRESETS["near-collinear"], self.run_program("--json").stdout)
        self.close(data["fits"][0]["weights"][0], -7, tolerance=1e-10)
        self.close(data["fits"][0]["weights"][1], 10, tolerance=1e-10)
        self.assertLess(data["fits"][-1]["weight_norm"], data["fits"][0]["weight_norm"])

    def test_orthogonal_features_have_independent_shrinkage(self):
        strengths = (0, 0.125, 1, 1000)
        data = self.explore(PRESETS["orthogonal"], strengths)
        for fit, strength in zip(data["fits"], strengths):
            self.close(fit["bias"], 1)
            self.close(fit["weights"][0], 6 / (2 + strength))
            self.close(fit["weights"][1], -5.6 / (2.8 + strength))
            self.close(fit["effective_df"], 1 + 2 / (2 + strength) + 2.8 / (2.8 + strength))

    def test_rank_one_fit_has_minimum_norm(self):
        rows = tuple((t, 2 * t, 1 + 3 * t) for t in T)
        data = self.explore(rows, (0, 1, 100))
        self.assertEqual(data["rank"], 1)
        for fit in data["fits"]:
            strength = fit["lambda"]
            self.close(fit["weights"][0], 6 / (10 + strength))
            self.close(fit["weights"][1], 12 / (10 + strength))
            self.close(fit["weights"][1] - 2 * fit["weights"][0], 0, 1)
            self.close(fit["effective_df"], 1 + 10 / (10 + strength))

    def test_constant_features_and_singletons_leave_intercept_unpenalized(self):
        for rows in (((2, -3, -2), (2, -3, 4)), ((1000, -1000, 1000),),
                     ((0, 0, 0),), ((0, 0, -1000), (0, 0, 1000))):
            with self.subTest(rows=rows):
                data = self.explore(rows, (0, 0.1, 1000000))
                self.assertEqual(data["rank"], 0)
                for fit in data["fits"]:
                    self.assertEqual(fit["weights"], [0, 0])
                    self.assertEqual(fit["shrinkage"], [0, 0])
                    self.assertEqual(fit["effective_df"], 1)
                    self.close(fit["bias"], sum(row[2] for row in rows) / len(rows))
                    self.assertEqual(fit["regularized_condition"], 1 if fit["lambda"] else None)

    def test_noisy_data_satisfies_independent_normal_equations(self):
        rows = ((-3, 2, 4), (-1, 3, -2), (0, -1, 1), (2, 4, 7), (4, -2, -3))
        data = self.explore(rows, (0, 0.0625, 1, 32))
        means, _, _, centered = moments(rows)
        for fit in data["fits"]:
            bias, w1, w2 = map(rational, (fit["bias"], *fit["weights"]))
            errors = [bias + w1 * rational(x) + w2 * rational(z) - rational(y) for x, z, y in rows]
            self.close(float(sum(errors) / len(rows)), 0, 1)
            for j, weight in enumerate((w1, w2)):
                gradient = sum(error * rational(row[j]) for error, row in zip(errors, rows)) / len(rows)
                gradient += rational(fit["lambda"]) * weight
                self.close(float(gradient), 0, 10)
            self.assertGreater(fit["data_loss"], 0)
        self.assertEqual(sum(row[2] for row in centered), 0)
        self.close(data["target_mean"], means[2])

    def test_effective_degrees_of_freedom_match_independent_hat_trace(self):
        for features in (((-1, 0), (0, 1), (1, -1), (2, 2)), ((-1, -2), (0, 0), (1, 2))):
            rows = tuple((x, z, i + 1) for i, (x, z) in enumerate(features))
            data = self.explore(rows, (0, 0.5, 10))
            for fit in data["fits"]:
                trace = Fraction(0)
                for i in range(len(rows)):
                    basis_target = tuple((x, z, int(j == i)) for j, (x, z) in enumerate(features))
                    predictions = fit_oracle(basis_target, fit["lambda"])[2]
                    trace += predictions[i]
                self.close(fit["effective_df"], trace, tolerance=1e-11)

    def test_regularization_path_trades_fit_for_smaller_weights(self):
        rows = PRESETS["near-collinear"]
        strengths = (0, 1e-6, 0.001, 0.01, 0.1, 1, 10, 1000000)
        data = self.explore(rows, strengths)
        losses = [fit["data_loss"] for fit in data["fits"]]
        norms = [fit["weight_norm"] for fit in data["fits"]]
        dfs = [fit["effective_df"] for fit in data["fits"]]
        conditions = [fit["regularized_condition"] for fit in data["fits"]]
        self.assertEqual(losses, sorted(losses))
        self.assertEqual(norms, sorted(norms, reverse=True))
        self.assertEqual(dfs, sorted(dfs, reverse=True))
        self.assertEqual(conditions, sorted(conditions, reverse=True))
        reordered = self.explore(rows, (10, 0, 0.1))
        self.assertEqual([fit["lambda"] for fit in reordered["fits"]], [10, 0, 0.1])

    def test_data_and_coordinate_symmetries(self):
        rows = ((-2, 1, 3), (-1, 4, -2), (1, -2, 5), (3, 2, 1))
        base = self.explore(rows, (0, 0.25, 3))
        transformed = (
            (rows[::-1], "reverse"), (rows * 3, "repeat"),
            (tuple((x + 50, z - 20, y + 7) for x, z, y in rows), "translate"),
            (tuple((z, x, y) for x, z, y in rows), "swap"),
            (tuple((-x, z, y) for x, z, y in rows), "reflect"),
            (tuple((x, z, -2 * y) for x, z, y in rows), "scale_target"),
        )
        for alternate_rows, name in transformed:
            with self.subTest(transformation=name):
                alternate = self.explore(alternate_rows, (0, 0.25, 3))
                for expected, actual in zip(base["fits"], alternate["fits"]):
                    self.close(actual["effective_df"], expected["effective_df"])
                    self.close(actual["data_loss"], expected["data_loss"] * (4 if name == "scale_target" else 1), 1)
                    if name == "translate":
                        self.close(actual["bias"], expected["bias"] + 7 - 50 * expected["weights"][0]
                                   + 20 * expected["weights"][1], 1)
                    expected_weights = expected["weights"][:]
                    if name == "swap":
                        expected_weights.reverse()
                    elif name == "reflect":
                        expected_weights[0] *= -1
                    elif name == "scale_target":
                        expected_weights = [-2 * value for value in expected_weights]
                    for a, b in zip(actual["weights"], expected_weights):
                        self.close(a, b, 1)

    def test_seeded_fits_match_exact_rational_solutions(self):
        generator = random.Random(41893)
        for case in range(16):
            rows = tuple((generator.randint(-16, 16) / 4, generator.randint(-16, 16) / 4,
                          generator.randint(-20, 20) / 2) for _ in range(generator.randint(2, 12)))
            with self.subTest(case=case):
                self.explore(rows, (0, 0.03125, 2))

    def test_numerical_rank_cutoff_does_not_truncate_positive_ridge(self):
        rows = tuple((x, z, z * 1000000) for x in (-1000, 1000) for z in (-1e-6, 1e-6))
        data = self.explore(rows, (0, 1e-6, 1))
        self.assertEqual(data["rank"], 1)
        self.assertGreater(data["eigenvalues"][1], 0)
        self.assertLess(data["eigenvalues"][1], data["rank_threshold"])
        self.close(data["fits"][0]["weight_norm"], 0, 1e-12)
        self.assertGreater(data["fits"][1]["weights"][1], 0.99)
        self.assertGreater(data["fits"][1]["shrinkage"][1], 0)
        self.assertEqual(data["fits"][0]["effective_df"], 2)
        self.assertGreater(data["fits"][1]["effective_df"], 2)
        # The weak direction is rotated relative to the feature axes. A rounded
        # elimination coefficient must not create a spurious target component.
        rotated = tuple((100 * t, 100 * t + 2 ** -20 * q, 3 * t + q / 8) for t, q in zip(T, Q))
        rotated_data = self.explore(rotated, (0, 1e-6, 1))
        self.assertEqual(rotated_data["rank"], 1)
        self.assertGreater(rotated_data["fits"][1]["weight_norm"], rotated_data["fits"][0]["weight_norm"])

    def test_adjacent_values_and_maximum_bounds(self):
        adjacent = ((1, 2, -1), (math.nextafter(1, 2), 2, 1))
        data = self.explore(adjacent, (0, 1e-6))
        self.assertEqual(data["rank"], 1)
        self.close(data["fits"][0]["weights"][0], 2 ** 53, tolerance=1e-12)
        self.assertLess(data["fits"][0]["data_loss"], 1e-20)
        self.close(data["fits"][1]["weights"][0], fit_oracle(adjacent, 1e-6)[1][0], tolerance=1e-12)
        rows = tuple((1000 if i % 2 else -1000, 1000 if i % 3 else -1000,
                      1000 if i % 5 else -1000) for i in range(256))
        self.explore(rows, (0, 1e-6, 1000000))
        collinear = ((-1000, -1000, -1000), (1000, 1000, 1000))
        large = self.explore(collinear, (0, 1e-6, 1))
        for fit in large["fits"]:
            expected = Fraction(1000000) / (Fraction(2000000) + rational(fit["lambda"]))
            for weight in fit["weights"]:
                self.close(weight, expected, tolerance=1e-12)
        self.explore((("-1e-6", "1e-6", "-1e-6"), ("1e-6", "-1e-6", "1e-6")), (0, 1e-6, 1000000))
        self.explore((("-0", "+0", "-0"),), (0, 1e-6))

    def test_file_input_help_and_terminal_output(self):
        rows = ((-1.25, 0.5, 3.75), (0.75, -2.5, -1.25), (2.25, 1.5, 0.5), (3.5, -0.75, 2.25))
        path = self.directory / "points with spaces.txt"
        path.write_text(serialize(rows), encoding="utf-8")
        file_output = self.run_program("--input", path, "--json")
        self.assertEqual(self.validate(rows, file_output.stdout), self.explore(rows))
        help_text = self.run_program("--help").stdout
        for option in ("--input", "--example", "--lambdas", "--json"):
            self.assertIn(option, help_text)
        human = self.run_program("--input", path)
        lines = human.stdout.splitlines()
        table_start = lines.index("lambda  bias  w1  w2  data_loss  penalty  objective  weight_norm") + 1
        numeric_rows = []
        for line in lines[table_start:]:
            if not line.strip():
                break
            numeric_rows.append(list(map(float, line.split())))
        fits = json.loads(file_output.stdout)["fits"]
        self.assertEqual(len(numeric_rows), len(fits))
        for row, fit in zip(numeric_rows, fits):
            self.assertEqual(row, [fit["lambda"], fit["bias"], *fit["weights"], fit["data_loss"],
                                   fit["penalty"], fit["objective"], fit["weight_norm"]])
        spectral_start = lines.index("lambda  shrink_max  shrink_min  effective_df  regularized_condition") + 1
        for line, fit in zip(lines[spectral_start:], fits):
            self.assertEqual(list(map(float, line.split())),
                             [fit["lambda"], *fit["shrinkage"], fit["effective_df"], fit["regularized_condition"]])

    def test_invalid_options(self):
        cases = [
            ("--unknown",), ("near-collinear",), ("--example",), ("--example", "unknown"),
            ("--input",), ("--input", ""), ("--input", self.directory / "missing.txt"),
            ("--lambdas",), ("--json", "--json"), ("--help", "--json"),
            ("--example", "collinear", "--input", "-"),
            ("--input", "-", "--input", "-"), ("--example", "collinear", "--example", "orthogonal"),
            ("--lambdas", "1", "--lambdas", "2"),
        ]
        for values in ("", ",", "1,", ",1", "1,,2", "0,0", "1,1.0", "0,-0", "-1", "1e-7",
                       "1000001", "nan", "inf", "0x1p0", "1_0", "1e999", "1e-999", ".", "1e",
                       "0,1,2,3,4,5,6,7,8"):
            cases.append(("--lambdas", values))
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, input_text=serialize(PRESETS["collinear"]), expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())

    def test_invalid_datasets(self):
        cases = ["", "0\n", "257\n", "-1\n", "1.5\n", "one\n", "1\n", "1\n1 2\n",
                 "2\n1 2 3\n", "1\n1 2 3 extra\n", "1\n1 2 3 4 5 6\n"]
        for value in ("nan", "NaN", "inf", "-Infinity", "0x1p0", "1_0", "1e-7", "-1e-7",
                      "1001", "-1001", "1e999", "1e-999", ".", "1e"):
            for column in range(3):
                row = ["0", "0", "0"]
                row[column] = value
                cases.append("1\n" + " ".join(row) + "\n")
        for input_text in cases:
            with self.subTest(input_text=input_text):
                result = self.run_program("--input", "-", "--json", input_text=input_text, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
