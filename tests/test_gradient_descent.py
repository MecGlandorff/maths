#!/usr/bin/env python3
"""Check affine gradient descent against exact losses, iterates, and spectra."""

from decimal import Decimal, localcontext
from fractions import Fraction
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
CENTERED = tuple(zip((-2, -1, 0, 1, 2), (-3, -1, 1, 3, 5)))
SHIFTED = tuple((x + 100, y) for x, y in CENTERED)
CONSTANT = tuple((2, y) for _, y in CENTERED)
KEYS = {
    "samples", "hessian", "eigenvalues", "rank", "condition_number",
    "learning_rate", "stable_rate_upper_bound", "rate_regime", "contraction_factor",
    "reference", "requested_steps", "completed_steps", "stop_reason", "trajectory",
}


def rational(value):
    """Use the exact value of each parsed double in the independent oracle."""
    return Fraction(float(value))


def serialize(rows):
    return f"{len(rows)}\n" + "\n".join(f"{x} {y}" for x, y in rows) + "\n"


def moments(rows):
    data = [(rational(x), rational(y)) for x, y in rows]
    count = len(data)
    mean_x = sum(x for x, _ in data) / count
    mean_y = sum(y for _, y in data) / count
    variance = sum((x - mean_x) ** 2 for x, _ in data) / count
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in data) / count
    mean_square = sum(x * x for x, _ in data) / count
    if variance:
        weight = covariance / variance
        bias = mean_y - weight * mean_x
    else:
        bias = mean_y / (1 + mean_x * mean_x)
        weight = mean_x * bias
    loss = sum((bias + weight * x - y) ** 2 for x, y in data) / (2 * count)
    return mean_x, variance, mean_square, bias, weight, loss


def spectrum(rows):
    mean_x, variance, mean_square, *_ = moments(rows)
    with localcontext() as context:
        context.prec = 90

        def dec(value):
            return Decimal(value.numerator) / Decimal(value.denominator)

        trace = 1 + dec(mean_square)
        discriminant = ((1 - dec(mean_square)) ** 2 + 4 * dec(mean_x) ** 2).sqrt()
        maximum = (trace + discriminant) / 2
        minimum = dec(variance) / maximum
        return float(minimum), float(maximum)


def exact_state(rows, bias, weight):
    """Differentiate the sample loss directly, independently of centered moments."""
    data = [(rational(x), rational(y)) for x, y in rows]
    residuals = [bias + weight * x - y for x, y in data]
    loss = sum(error * error for error in residuals) / (2 * len(data))
    gradient = (sum(residuals) / len(data),
                sum(error * x for error, (x, _) in zip(residuals, data)) / len(data))
    return loss, gradient


def exact_trajectory(rows, rate, steps, start=(0, 0)):
    bias, weight = map(rational, start)
    rate = rational(rate)
    result = []
    for step in range(steps + 1):
        loss, gradient = exact_state(rows, bias, weight)
        result.append((bias, weight, loss, gradient))
        if step != steps:
            bias, weight = bias - rate * gradient[0], weight - rate * gradient[1]
    return result


class GradientDescentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-gradient-descent-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "gradient_descent"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "gradient_descent.cpp"), "-o", str(cls.binary)]
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

    def close(self, actual, expected, scale=0, tolerance=3e-11):
        expected = float(expected)
        self.assertTrue(math.isfinite(actual), actual)
        allowed = tolerance * max(abs(expected), abs(scale))
        self.assertLessEqual(abs(actual - expected), allowed,
                             f"{actual!r} != {expected!r} (tolerance {allowed!r})")

    def finite_json(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.finite_json(item)
        elif isinstance(value, list):
            for item in value:
                self.finite_json(item)
        elif value is not None and not isinstance(value, str):
            self.assertIn(type(value), (int, float))
            self.assertTrue(math.isfinite(value), value)

    def validate(self, rows, output, steps=12, rate=None, start=(0, 0), limited=False):
        data = json.loads(output)
        self.assertEqual(set(data), KEYS)
        self.finite_json(data)
        self.assertIs(type(data["samples"]), int)
        self.assertEqual(data["samples"], len(rows))
        mean_x, variance, mean_square, bias, weight, loss = moments(rows)
        self.assertEqual(len(data["hessian"]), 2)
        for actual, expected in zip(data["hessian"], ((1, mean_x), (mean_x, mean_square))):
            self.assertEqual(len(actual), 2)
            for a, b in zip(actual, expected):
                self.close(a, b, tolerance=3e-14)
        minimum, maximum = spectrum(rows)
        self.assertEqual(len(data["eigenvalues"]), 2)
        for actual, expected in zip(data["eigenvalues"], (minimum, maximum)):
            self.close(actual, expected, tolerance=5e-12)
        self.assertEqual(data["rank"], 2 if variance else 1)
        if variance:
            self.close(data["condition_number"], maximum / minimum, tolerance=8e-12)
        else:
            self.assertIsNone(data["condition_number"])
        if rate is None:
            rate = 1 / maximum
        else:
            rate = float(rate)
        self.close(data["learning_rate"], rate, tolerance=3e-14)
        self.close(data["stable_rate_upper_bound"], 2 / maximum, tolerance=3e-14)
        # Test exact boundary classification separately using an integer spectrum.
        product = rate * maximum
        if abs(product - 2) > 1e-12:
            self.assertEqual(data["rate_regime"], "contracting" if product < 2 else "unstable")
        positive = (minimum, maximum) if variance else (maximum,)
        factor = max(abs(1 - rate * value) for value in positive)
        self.close(data["contraction_factor"], factor, 1, tolerance=3e-14)
        reference = data["reference"]
        self.assertEqual(set(reference), {"bias", "weight", "loss"})
        self.close(reference["bias"], bias, 1)
        self.close(reference["weight"], weight, 1)
        energy = sum(float(y) ** 2 for _, y in rows) / (2 * len(rows))
        self.close(reference["loss"], loss, energy * 1e-12, tolerance=3e-11)
        self.assertGreaterEqual(reference["loss"], 0)
        self.assertEqual(data["requested_steps"], steps)
        self.assertEqual(data["stop_reason"], "magnitude_limit" if limited else "steps_completed")
        completed = data["completed_steps"]
        self.assertIs(type(completed), int)
        if limited:
            self.assertLess(completed, steps)
        else:
            self.assertEqual(completed, steps)
        self.assertEqual(len(data["trajectory"]), completed + 1)
        previous = None
        max_x = max(abs(float(x)) for x, _ in rows)
        max_y = max(abs(float(y)) for _, y in rows)
        for index, state in enumerate(data["trajectory"]):
            self.assertEqual(set(state), {"step", "bias", "weight", "loss", "gradient"})
            self.assertIs(type(state["step"]), int)
            self.assertEqual(state["step"], index)
            self.assertLessEqual(abs(state["bias"]), 1e100)
            self.assertLessEqual(abs(state["weight"]), 1e100)
            self.assertEqual(len(state["gradient"]), 2)
            expected_loss, gradient = exact_state(
                rows, rational(state["bias"]), rational(state["weight"]))
            residual_scale = abs(state["bias"]) + abs(state["weight"]) * max_x + max_y
            self.close(state["loss"], expected_loss, residual_scale ** 2 * 1e-12)
            self.assertGreaterEqual(state["loss"], 0)
            self.close(state["gradient"][0], gradient[0], residual_scale)
            self.close(state["gradient"][1], gradient[1], residual_scale * max_x)
            if previous is not None:
                for label, component in (("bias", 0), ("weight", 1)):
                    expected = previous[label] - rate * previous["gradient"][component]
                    scale = abs(previous[label]) + abs(rate * previous["gradient"][component])
                    self.close(state[label], expected, scale, tolerance=8e-13)
            previous = state
        self.close(data["trajectory"][0]["bias"], rational(start[0]))
        self.close(data["trajectory"][0]["weight"], rational(start[1]))
        if limited:
            last = data["trajectory"][-1]
            candidate = (last["bias"] - rate * last["gradient"][0],
                         last["weight"] - rate * last["gradient"][1])
            self.assertGreater(max(map(abs, candidate)), 1e100)
        return data

    def explore(self, rows, steps=12, rate=None, start=(0, 0), limited=False):
        arguments = ["--input", "-", "--steps", steps, "--start", *start, "--json"]
        if rate is not None:
            arguments += ["--rate", rate]
        result = self.run_program(*arguments, input_text=serialize(rows),
                                  expected_code=2 if limited else 0)
        return self.validate(rows, result.stdout, steps, rate, start, limited)

    def check_exact_iterates(self, data, rows, rate, steps, start=(0, 0)):
        exact = exact_trajectory(rows, rate, steps, start)
        for state, (bias, weight, loss, gradient) in zip(data["trajectory"], exact):
            self.close(state["bias"], bias, 1, tolerance=5e-12)
            self.close(state["weight"], weight, 1, tolerance=5e-12)
            self.close(state["loss"], loss, 1e-20, tolerance=5e-12)
            for actual, expected in zip(state["gradient"], gradient):
                self.close(actual, expected, 1, tolerance=5e-12)

    def test_presets_and_default_input(self):
        for name, rows in (("centered", CENTERED), ("shifted", SHIFTED), ("constant", CONSTANT)):
            with self.subTest(example=name):
                data = self.validate(rows, self.run_program("--example", name, "--json").stdout)
                self.assertEqual(data, self.explore(rows))
        default = self.validate(CENTERED, self.run_program("--json").stdout)
        self.assertEqual(default, self.explore(CENTERED))
        self.assertEqual(default["hessian"], [[1, 0], [0, 2]])
        self.assertEqual(default["reference"], {"bias": 1, "weight": 2, "loss": 0})
        self.assertEqual(default["eigenvalues"], [1, 2])
        self.assertEqual(default["learning_rate"], 0.5)
        human = self.run_program()
        self.assertTrue(human.stdout.strip())
        self.assertFalse(human.stdout.lstrip().startswith("{"))

    def test_diagonal_hessian_has_analytic_geometric_modes(self):
        start = (-3, -4)
        for rate in (0.125, 0.5, 0.75):
            with self.subTest(rate=rate):
                data = self.explore(CENTERED, steps=20, rate=rate, start=start)
                for state in data["trajectory"]:
                    step = state["step"]
                    bias = 1 + (start[0] - 1) * (1 - rate) ** step
                    weight = 2 + (start[1] - 2) * (1 - 2 * rate) ** step
                    self.close(state["bias"], bias, 1, tolerance=3e-14)
                    self.close(state["weight"], weight, 1, tolerance=3e-14)
                    self.close(state["loss"], (bias - 1) ** 2 / 2 + (weight - 2) ** 2,
                               1e-25, tolerance=3e-12)
                losses = [state["loss"] for state in data["trajectory"]]
                self.assertEqual(losses, sorted(losses, reverse=True))

    def test_noisy_fit_and_simultaneous_steps_against_rationals(self):
        rows = ((-3, 5), (-1, -2), (0, 3), (2, 4), (4, -1))
        start = (1.25, -0.75)
        data = self.explore(rows, rate=0.0625, steps=15, start=start)
        self.check_exact_iterates(data, rows, 0.0625, 15, start)
        self.assertGreater(data["reference"]["loss"], 0)
        loss, gradient = exact_state(rows, *moments(rows)[3:5])
        self.assertEqual(gradient, (0, 0))
        self.close(data["reference"]["loss"], loss)
        initial = data["trajectory"][0]
        epsilon = Fraction(1, 2 ** 20)
        for coordinate in (0, 1):
            plus, minus = list(map(rational, start)), list(map(rational, start))
            plus[coordinate] += epsilon
            minus[coordinate] -= epsilon
            finite_difference = (exact_state(rows, *plus)[0] - exact_state(rows, *minus)[0]) / (2 * epsilon)
            self.close(initial["gradient"][coordinate], finite_difference)

    def test_rank_one_minimum_norm_and_preserved_nullspace(self):
        for rows in (CONSTANT, ((0, -2), (0, 4)), ((-3, 7),)):
            c = float(rows[0][0])
            for start in ((0, 0), (3, -4)):
                with self.subTest(rows=rows, start=start):
                    data = self.explore(rows, steps=10, start=start)
                    self.assertEqual(data["rank"], 1)
                    self.close(data["contraction_factor"], 0, 1, tolerance=3e-14)
                    invariant = start[1] - c * start[0]
                    for state in data["trajectory"]:
                        self.close(state["weight"] - c * state["bias"], invariant, 1)
                    final = data["trajectory"][-1]
                    self.close(final["loss"], data["reference"]["loss"], 1e-20)
                    mean_y = sum(float(y) for _, y in rows) / len(rows)
                    self.close(final["bias"] + c * final["weight"], mean_y, 1)
                    if start == (0, 0):
                        self.close(final["bias"], data["reference"]["bias"], 1)
                        self.close(final["weight"], data["reference"]["weight"], 1)
        nonzero = self.explore(CONSTANT, start=(3, -4))
        self.assertNotEqual(nonzero["trajectory"][-1]["bias"], nonzero["reference"]["bias"])

    def test_shift_preserves_fit_but_makes_convergence_slower(self):
        centered = self.explore(CENTERED, steps=40)
        shifted = self.explore(SHIFTED, steps=40)
        self.assertEqual(shifted["reference"], {"bias": -199, "weight": 2, "loss": 0})
        self.assertGreater(shifted["condition_number"], 1e7 * centered["condition_number"])
        self.assertGreater(shifted["contraction_factor"], centered["contraction_factor"])
        self.assertGreater(shifted["trajectory"][-1]["loss"], 1)
        self.assertLess(centered["trajectory"][-1]["loss"], 1e-20)
        self.assertLess(shifted["learning_rate"], centered["learning_rate"] / 1000)

    def test_boundary_oscillation_and_unstable_or_unexcited_modes(self):
        boundary = self.explore(CENTERED, rate=1, steps=8, start=(1, 0))
        self.assertEqual(boundary["rate_regime"], "boundary")
        self.assertEqual(boundary["contraction_factor"], 1)
        for state in boundary["trajectory"]:
            self.assertEqual(state["weight"], 0 if state["step"] % 2 == 0 else 4)
            self.assertEqual(state["loss"], 4)
        unstable = self.explore(CENTERED, rate=1.25, steps=8, start=(1, 0))
        self.assertEqual(unstable["rate_regime"], "unstable")
        self.assertEqual(unstable["contraction_factor"], 1.5)
        self.check_exact_iterates(unstable, CENTERED, 1.25, 8, (1, 0))
        self.assertGreater(unstable["trajectory"][-1]["loss"], unstable["trajectory"][0]["loss"])
        for start in ((0, 2), (1, 2)):
            unexcited = self.explore(CENTERED, rate=1.25, steps=12, start=start)
            self.assertEqual(unexcited["rate_regime"], "unstable")
            losses = [state["loss"] for state in unexcited["trajectory"]]
            self.assertEqual(losses, sorted(losses, reverse=True))

    def test_permutation_replication_and_target_symmetries(self):
        rows = ((-3, 1), (0, 4), (2, -2), (4, 5))
        baseline = self.explore(rows, rate=0.0625, steps=12, start=(0.5, -1))
        for equivalent in (rows[::-1], rows * 3):
            alternate = self.explore(equivalent, rate=0.0625, steps=12, start=(0.5, -1))
            self.assertEqual(alternate["hessian"], baseline["hessian"])
            for label in ("bias", "weight", "loss"):
                self.close(alternate["reference"][label], baseline["reference"][label], 1)
            for actual, expected in zip(alternate["trajectory"], baseline["trajectory"]):
                for label in ("bias", "weight", "loss"):
                    self.close(actual[label], expected[label], 1)
                for a, b in zip(actual["gradient"], expected["gradient"]):
                    self.close(a, b, 1)
        scaled = self.explore(tuple((x, -2 * y) for x, y in rows),
                              rate=0.0625, steps=12, start=(-1, 2))
        reflected = self.explore(tuple((-x, y) for x, y in rows),
                                 rate=0.0625, steps=12, start=(0.5, 1))
        for original, scaled_state, reflected_state in zip(
                baseline["trajectory"], scaled["trajectory"], reflected["trajectory"]):
            for label in ("bias", "weight"):
                self.close(scaled_state[label], -2 * original[label], 1)
            self.close(scaled_state["loss"], 4 * original["loss"])
            self.close(reflected_state["bias"], original["bias"], 1)
            self.close(reflected_state["weight"], -original["weight"], 1)
            self.close(reflected_state["loss"], original["loss"])

    def test_seeded_datasets_have_correct_gradients_and_decreasing_loss(self):
        generator = random.Random(71341)
        for index in range(16):
            rows = tuple((generator.randint(-16, 16) / 4, generator.randint(-20, 20) / 4)
                         for _ in range(generator.randint(2, 12)))
            with self.subTest(case=index):
                start = (generator.randint(-4, 4) / 2, generator.randint(-4, 4) / 2)
                data = self.explore(rows, steps=18, rate=0.03125, start=start)
                self.check_exact_iterates(data, rows, 0.03125, 18, start)
                losses = [state["loss"] for state in data["trajectory"]]
                self.assertEqual(losses, sorted(losses, reverse=True))
                self.assertGreaterEqual(losses[-1] + 1e-12, data["reference"]["loss"])

    def test_nearly_identical_features_retain_the_small_eigenvalue(self):
        adjacent = ((1, -1), (math.nextafter(1, 2), 0),
                    (math.nextafter(math.nextafter(1, 2), 2), 1))
        adjacent_data = self.explore(adjacent, steps=0)
        self.assertEqual(adjacent_data["rank"], 2)
        self.assertGreater(adjacent_data["eigenvalues"][0], 0)
        self.close(adjacent_data["reference"]["weight"], 2 ** 52)
        self.assertLess(adjacent_data["reference"]["loss"], 1e-20)
        rows = (("999999.99999999976716935634613037109375", -1000000),
                ("999999.999999999883584678173065185546875", 0),
                ("1000000", 1000000))
        data = self.explore(rows, steps=0)
        self.assertEqual(data["rank"], 2)
        self.assertGreater(data["eigenvalues"][0], 0)
        self.assertGreater(data["condition_number"], 1e43)
        self.close(data["reference"]["weight"], 1000000 * 2 ** 33, tolerance=3e-14)
        self.assertLess(data["reference"]["loss"], 1e-10)
        constant = self.explore(((1000000, -1000000), (1000000, 1000000)), steps=0)
        self.assertEqual(constant["rank"], 1)
        self.assertEqual(constant["eigenvalues"][0], 0)

    def test_magnitude_limit_preserves_last_finite_step(self):
        rows = ((0, 1),)
        data = self.explore(rows, steps=1000, rate=1000000, limited=True)
        self.assertEqual(data["completed_steps"], 16)
        self.check_exact_iterates(data, rows, 1000000, 16)
        extreme = self.explore(((1000000, 1000000),), steps=1000, rate=1000000, limited=True)
        self.assertEqual(extreme["completed_steps"], 5)
        human = self.run_program("--input", "-", "--rate", 1000000, "--steps", 1000,
                                 input_text=serialize(rows), expected_code=2)
        self.assertTrue(human.stdout.strip())

    def test_maximum_input_and_parameter_boundaries(self):
        rows = tuple(((-1 if index % 2 else 1) * 1000000,
                      (-1 if index % 3 else 1) * 1000000) for index in range(256))
        self.explore(rows, steps=1000, rate="1e-15", start=(-1000000, 1000000))
        self.explore(((-1000000, 1000000), (1000000, -1000000)), steps=0,
                     rate=1000000, start=(1000000, -1000000))
        tiny = self.explore((("-1e-6", "1e-6"), ("1e-6", "-1e-6")), steps=4,
                            rate="1e-15", start=("1e-6", "-1e-6"))
        self.assertEqual(tiny["rank"], 2)
        self.explore((("-0", "0"),), steps=0, start=("+0", "-0"))

    def test_file_input_and_help(self):
        path = self.directory / "points with spaces.txt"
        path.write_text(serialize(CENTERED), encoding="utf-8")
        result = self.run_program("--input", path, "--json", "--steps", 0)
        self.assertEqual(self.validate(CENTERED, result.stdout, steps=0),
                         self.explore(CENTERED, steps=0))
        help_text = self.run_program("--help").stdout
        for option in ("--example", "--input", "--rate", "--steps", "--start", "--json"):
            self.assertIn(option, help_text)
        rows = ((0.125, -0.375), (0.5, 0.625), (1.25, 0.875))
        rate, start = 0.12345678901234566, (1 / 3, -1 / 7)
        data = self.explore(rows, steps=3, rate=rate, start=start)
        human = self.run_program("--input", "-", "--steps", 3, "--rate", rate,
                                 "--start", *start, input_text=serialize(rows)).stdout
        lines = human.splitlines()
        heading = lines.index("step  bias  weight  loss  gradient_bias  gradient_weight")
        table = [list(map(float, line.split())) for line in lines[heading + 1:-1]]
        self.assertEqual(len(table), len(data["trajectory"]))
        for actual, state in zip(table, data["trajectory"]):
            self.assertEqual(actual, [state["step"], state["bias"], state["weight"],
                                      state["loss"], *state["gradient"]])
        printed_rate = next(line.split(": ", 1)[1] for line in lines
                            if line.startswith("Learning rate: "))
        self.assertEqual(float(printed_rate), data["learning_rate"])

    def test_invalid_cli_arguments(self):
        cases = [
            ("--unknown",), ("centered",), ("--example",), ("--input",),
            ("--rate",), ("--steps",), ("--start",), ("--start", "1"),
            ("--example", "unknown"), ("--example", "centered", "--input", "-"),
            ("--json", "--json"), ("--help", "--json"), ("--json", "--help"),
            ("--input", self.directory / "missing.txt"),
        ]
        for option, value in (("--example", "centered"), ("--input", "-"),
                              ("--rate", "0.5"), ("--steps", "1")):
            cases.append((option, value, option, value))
        cases.append(("--start", "0", "0", "--start", "0", "0"))
        cases += [("--steps", value) for value in ("-1", "1001", "1.0", "1e1", "x", "999999999999999999999")]
        cases += [("--rate", value) for value in ("0", "-0.5", "1e-16", "1000001", "nan", "inf", "0x1p0", "1_0", "1e999", "1e-999")]
        for value in ("nan", "-inf", "1e-7", "1000001", "-1000001", "0x1p0", "1_0", ".", "1e"):
            cases.extend((("--start", value, "0"), ("--start", "0", value)))
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, input_text=serialize(CENTERED), expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())

    def test_invalid_datasets(self):
        cases = ["", "0\n", "257\n", "-1\n", "1.5\n", "one\n", "1\n",
                 "1\n2\n", "2\n1 2\n", "1\n1 2 extra\n", "1\n1 2 3 4\n"]
        for value in ("nan", "NaN", "inf", "-Infinity", "0x1p0", "1_0", "1e-7",
                      "-1e-7", "1000001", "-1000001", "1e999", "1e-999", ".", "1e"):
            cases.extend((f"1\n{value} 0\n", f"1\n0 {value}\n"))
        for input_text in cases:
            with self.subTest(input_text=input_text):
                result = self.run_program("--input", "-", "--json", input_text=input_text, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
