#!/usr/bin/env python3
"""Verify neural-network derivatives through the CLI and independent arithmetic."""

import copy
from decimal import Decimal, localcontext
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
DEMO = {
    "x": [[-1, -1], [-1, 1], [1, -1], [1, 1]],
    "y": [0, 1, 1, 0],
    "w1": [[0.5, -0.7, 0.3], [-0.4, 0.6, 0.8]],
    "b1": [0.1, -0.2, 0.05], "w2": [0.7, -0.5, 0.4], "b2": -0.1,
}
PARAMETERS = ("w1", "b1", "w2", "b2")
JSON_KEYS = {
    "samples", "features", "hidden_units", "steps", "learning_rate", "initial_loss",
    "inputs", "targets", "parameters", "forward", "backward",
}


def decimal(value):
    return Decimal.from_float(value) if isinstance(value, float) else Decimal(value)


def flatten(value):
    if isinstance(value, (tuple, list)):
        for item in value:
            yield from flatten(item)
    else:
        yield value


def serialize(data):
    n, d, h = len(data["x"]), len(data["x"][0]), len(data["b1"])
    values = [str(item) for key in ("x", "y", *PARAMETERS)
              for item in flatten(data[key])]
    return f"{n} {d} {h}\n" + " ".join(values) + "\n"


def reference(data):
    """Evaluate the defining functions and chain rule with 90-digit arithmetic.

    This uses cosh for the tanh derivative and the direct sigmoid/softplus
    definitions, independently of the executable's cancellation-safe branches.
    """
    with localcontext() as context:
        context.prec = 90
        x = [[decimal(v) for v in row] for row in data["x"]]
        y = list(map(decimal, data["y"]))
        w = [[decimal(v) for v in row] for row in data["w1"]]
        b, v = (list(map(decimal, data[key])) for key in ("b1", "w2"))
        c = decimal(data["b2"])
        n, d, h = len(x), len(x[0]), len(b)
        z = [[sum(xi[j] * w[j][k] for j in range(d)) + b[k]
              for k in range(h)] for xi in x]
        activation = [[(zk.exp() - (-zk).exp()) / (zk.exp() + (-zk).exp())
                       for zk in row] for row in z]
        slopes = [[(2 / (zk.exp() + (-zk).exp())) ** 2 for zk in row] for row in z]
        logits = [sum(ai[k] * v[k] for k in range(h)) + c for ai in activation]
        p = [1 / (1 + (-s).exp()) for s in logits]
        losses = [(1 + s.exp()).ln() - yi * s for s, yi in zip(logits, y)]
        ds = [(pi - yi) / n for pi, yi in zip(p, y)]
        dh = [[di * vk for vk in v] for di in ds]
        dz = [[dh[i][k] * slopes[i][k] for k in range(h)] for i in range(n)]
        dw = [[sum(x[i][j] * dz[i][k] for i in range(n))
               for k in range(h)] for j in range(d)]
        db = [sum(row[k] for row in dz) for k in range(h)]
        dv = [sum(activation[i][k] * ds[i] for i in range(n)) for k in range(h)]
        dc = sum(ds)
        dx = [[sum(dz[i][k] * w[j][k] for k in range(h)) for j in range(d)]
              for i in range(n)]
        norm = sum(item * item for item in flatten([dw, db, dv, dc])).sqrt()
        return {
            "forward": {
                "hidden_preactivations": z, "hidden_activations": activation,
                "hidden_slopes": slopes, "logits": logits, "probabilities": p,
                "sample_losses": losses, "loss": sum(losses) / n,
            },
            "backward": {
                "logit_gradients": ds, "hidden_gradients": dh,
                "hidden_preactivation_gradients": dz, "w1": dw, "b1": db,
                "w2": dv, "b2": dc, "inputs": dx, "parameter_gradient_norm": norm,
            },
        }


def independent_loss(data):
    """Only the scalar objective: no derivative formulas or executable output."""
    with localcontext() as context:
        context.prec = 90
        loss = Decimal(0)
        for row, target in zip(data["x"], data["y"]):
            score = decimal(data["b2"])
            for k, output_weight in enumerate(data["w2"]):
                z = decimal(data["b1"][k])
                z += sum(decimal(x) * decimal(data["w1"][j][k])
                         for j, x in enumerate(row))
                e = (2 * z).exp()
                score += decimal(output_weight) * (e - 1) / (e + 1)
            loss += (1 + score.exp()).ln() - decimal(target) * score
        return loss / len(data["x"])


def coordinates(data, key):
    value = data[key]
    if key == "b2":
        return [()]
    if key in ("x", "w1"):
        return [(i, j) for i, row in enumerate(value) for j in range(len(row))]
    return [(i,) for i in range(len(value))]


def get_coordinate(data, key, indices):
    value = data[key]
    for index in indices:
        value = value[index]
    return value


def set_coordinate(data, key, indices, value):
    if not indices:
        data[key] = value
        return
    target = data[key]
    for index in indices[:-1]:
        target = target[index]
    target[indices[-1]] = value


def updated(data, gradient, rate):
    result = copy.deepcopy(data)
    for key in PARAMETERS:
        for indices in coordinates(data, key):
            value = get_coordinate(data, key, indices)
            derivative = float(get_coordinate(gradient, key, indices))
            set_coordinate(result, key, indices, value - rate * derivative)
    return result


def random_case(seed, n, d, h):
    rng = random.Random(seed)
    return {
        "x": [[rng.uniform(-1.2, 1.2) for _ in range(d)] for _ in range(n)],
        "y": [rng.uniform(0.05, 0.95) for _ in range(n)],
        "w1": [[rng.uniform(-0.8, 0.8) for _ in range(h)] for _ in range(d)],
        "b1": [rng.uniform(-0.3, 0.3) for _ in range(h)],
        "w2": [rng.uniform(-0.8, 0.8) for _ in range(h)],
        "b2": rng.uniform(-0.3, 0.3),
    }


class BackpropagationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-backpropagation-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "backpropagation"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "backpropagation.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, input_text=None, expected_code=0):
        result = subprocess.run(
            [str(self.binary), *(str(arg) for arg in arguments)], input=input_text,
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        if expected_code == 0:
            self.assertEqual(result.stderr, "")
        else:
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())
        return result

    def close(self, actual, expected, absolute=3e-13, relative=3e-12):
        expected = float(expected)
        self.assertTrue(math.isfinite(actual), actual)
        self.assertLessEqual(abs(actual - expected), absolute + relative * abs(expected),
                             f"{actual!r} != {expected!r}")

    def tree_close(self, actual, expected, absolute=3e-13, relative=3e-12):
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key in expected:
                self.tree_close(actual[key], expected[key], absolute, relative)
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.tree_close(a, b, absolute, relative)
        else:
            self.close(actual, expected, absolute, relative)

    def finite_json(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.finite_json(item)
        elif isinstance(value, list):
            for item in value:
                self.finite_json(item)
        else:
            self.assertIn(type(value), (int, float))
            self.assertTrue(math.isfinite(value), value)

    def analyze(self, data, *arguments):
        result = self.run_program("--input", "-", "--json", *arguments,
                                  input_text=serialize(data))
        parsed = json.loads(result.stdout)
        self.finite_json(parsed)
        return parsed

    def validate(self, actual, initial, steps=0, rate=1, trace=False):
        self.assertEqual(set(actual), JSON_KEYS | ({"trace"} if trace else set()))
        for key, expected in (("samples", len(initial["x"])),
                              ("features", len(initial["x"][0])),
                              ("hidden_units", len(initial["b1"])), ("steps", steps)):
            self.assertIs(type(actual[key]), int)
            self.assertEqual(actual[key], expected)
        self.assertEqual(actual["learning_rate"], rate)
        self.assertEqual(actual["inputs"], initial["x"])
        self.assertEqual(actual["targets"], initial["y"])
        self.close(actual["initial_loss"], independent_loss(initial))
        current = copy.deepcopy(initial)
        self.assertEqual(set(actual["parameters"]), set(PARAMETERS))
        current.update(actual["parameters"])
        if steps == 0:
            self.tree_close(actual["parameters"], {key: initial[key] for key in PARAMETERS},
                            absolute=0, relative=0)
        expected = reference(current)
        for key in ("forward", "backward"):
            self.tree_close(actual[key], expected[key])
        self.assertTrue(all(0 <= p <= 1 for p in actual["forward"]["probabilities"]))
        self.assertTrue(all(loss >= 0 for loss in actual["forward"]["sample_losses"]))
        self.finite_json(actual)
        if trace:
            records = actual["trace"]
            self.assertEqual(len(records), steps + 1)
            for index, entry in enumerate(records):
                self.assertEqual(set(entry), {"step", "loss", "parameter_gradient_norm"})
                self.assertIs(type(entry["step"]), int)
                self.assertEqual(entry["step"], index)
            self.close(records[0]["loss"], actual["initial_loss"])
            self.close(records[-1]["loss"], actual["forward"]["loss"])
            self.close(records[-1]["parameter_gradient_norm"],
                       actual["backward"]["parameter_gradient_norm"])

    def test_default_forward_and_chain_rule(self):
        actual = json.loads(self.run_program("--json").stdout)
        self.validate(actual, DEMO)
        self.close(actual["forward"]["loss"], 0.7633888953659993)

    def test_singleton_has_analytic_gradients(self):
        data = {"x": [[2]], "y": [0.25], "w1": [[0]], "b1": [0], "w2": [3], "b2": 0}
        actual = self.analyze(data, "--trace")
        self.validate(actual, data, trace=True)
        backward = actual["backward"]
        self.assertEqual(backward["logit_gradients"], [0.25])
        self.assertEqual(backward["w1"], [[1.5]])
        self.assertEqual(backward["b1"], [0.75])
        self.assertEqual(backward["w2"], [0])
        self.assertEqual(backward["b2"], 0.25)
        self.assertEqual(backward["inputs"], [[0]])
        self.close(actual["forward"]["loss"], math.log(2))

    def test_seeded_asymmetric_networks_and_soft_labels(self):
        for seed, shape in enumerate(((3, 2, 4), (2, 3, 2), (1, 4, 3), (5, 1, 2),
                                      (7, 5, 1), (4, 3, 5)), start=731):
            with self.subTest(seed=seed, shape=shape):
                data = random_case(seed, *shape)
                self.validate(self.analyze(data), data)

    def test_independent_finite_differences_for_every_parameter_and_input(self):
        checked = 0
        for seed, shape in ((21, (3, 2, 4)), (93, (2, 3, 2))):
            data = random_case(seed, *shape)
            actual = self.analyze(data)
            for key in (*PARAMETERS, "x"):
                for indices in coordinates(data, key):
                    with self.subTest(seed=seed, parameter=key, coordinate=indices):
                        plus, minus = copy.deepcopy(data), copy.deepcopy(data)
                        original = get_coordinate(data, key, indices)
                        step = 1e-5
                        set_coordinate(plus, key, indices, original + step)
                        set_coordinate(minus, key, indices, original - step)
                        denominator = (decimal(get_coordinate(plus, key, indices))
                                       - decimal(get_coordinate(minus, key, indices)))
                        numerical = (independent_loss(plus) - independent_loss(minus)) / denominator
                        analytic = get_coordinate(actual["backward"],
                                                  "inputs" if key == "x" else key, indices)
                        self.close(analytic, numerical, absolute=2e-10, relative=2e-8)
                        checked += 1
        self.assertEqual(checked, 40)

    def test_batch_duplication_preserves_parameter_gradients(self):
        data = random_case(97, 3, 2, 3)
        duplicate = copy.deepcopy(data)
        duplicate["x"] *= 2
        duplicate["y"] *= 2
        first, second = self.analyze(data), self.analyze(duplicate)
        self.close(first["forward"]["loss"], second["forward"]["loss"])
        for key in PARAMETERS:
            self.tree_close(first["backward"][key], second["backward"][key])
        for key in ("logit_gradients", "hidden_gradients", "hidden_preactivation_gradients", "inputs"):
            for expected, actual in zip(flatten(first["backward"][key] * 2),
                                        flatten(second["backward"][key])):
                self.close(actual, expected / 2)

    def test_sample_and_hidden_unit_permutations(self):
        data = random_case(144, 4, 2, 3)
        first = self.analyze(data)
        shuffled = copy.deepcopy(data)
        order = [2, 0, 3, 1]
        shuffled["x"] = [data["x"][i] for i in order]
        shuffled["y"] = [data["y"][i] for i in order]
        second = self.analyze(shuffled)
        for key in PARAMETERS:
            self.tree_close(first["backward"][key], second["backward"][key])
        self.tree_close(second["backward"]["inputs"],
                        [first["backward"]["inputs"][i] for i in order])
        self.tree_close(second["forward"]["probabilities"],
                        [first["forward"]["probabilities"][i] for i in order])
        hidden_order = [2, 0, 1]
        shuffled = copy.deepcopy(data)
        shuffled["w1"] = [[row[k] for k in hidden_order] for row in data["w1"]]
        for key in ("b1", "w2"):
            shuffled[key] = [data[key][k] for k in hidden_order]
        third = self.analyze(shuffled)
        self.close(third["forward"]["loss"], first["forward"]["loss"])
        self.tree_close(third["backward"]["inputs"], first["backward"]["inputs"])
        self.tree_close(third["backward"]["w1"],
                        [[row[k] for k in hidden_order] for row in first["backward"]["w1"]])

    def test_one_step_uses_simultaneous_parameter_updates(self):
        data = random_case(222, 3, 2, 3)
        rate = 0.125
        actual = self.analyze(data, "--steps", 1, "--rate", rate, "--trace")
        expected = updated(data, reference(data)["backward"], rate)
        self.tree_close(actual["parameters"], {key: expected[key] for key in PARAMETERS})
        self.validate(actual, data, steps=1, rate=rate, trace=True)
        self.assertLess(actual["forward"]["loss"], actual["initial_loss"])
        growing = {"x": [[10]], "y": [0], "w1": [[0]], "b1": [0], "w2": [10], "b2": 0}
        result = self.analyze(growing, "--steps", 1)
        self.assertEqual(result["parameters"], {"w1": [[-50]], "b1": [-5], "w2": [10], "b2": -0.5})
        self.validate(result, growing, steps=1)

    def test_short_training_trace_and_final_gradient_recomputation(self):
        data = random_case(555, 3, 2, 4)
        rate, steps = 0.3, 9
        actual = self.analyze(data, "--steps", steps, "--rate", rate, "--trace")
        self.validate(actual, data, steps=steps, rate=rate, trace=True)
        current = copy.deepcopy(data)
        for index in range(steps + 1):
            expected = reference(current)
            self.close(actual["trace"][index]["loss"], expected["forward"]["loss"])
            self.close(actual["trace"][index]["parameter_gradient_norm"],
                       expected["backward"]["parameter_gradient_norm"])
            if index < steps:
                current = updated(current, expected["backward"], rate)
        self.tree_close(actual["parameters"], {key: current[key] for key in PARAMETERS})

    def test_xor_learns_with_fixed_initialization(self):
        actual = json.loads(self.run_program("--steps", 1000, "--json").stdout)
        self.validate(actual, DEMO, steps=1000)
        self.assertLess(actual["forward"]["loss"], 0.01)
        for target, probability in zip(DEMO["y"], actual["forward"]["probabilities"]):
            self.assertLess(abs(probability - target), 0.01)

    def test_saturated_sigmoid_and_tanh_keep_small_derivatives(self):
        for sign in (-1, 1):
            data = {"x": [[1]], "y": [(sign + 1) / 2], "w1": [[10, 10, 10]],
                    "b1": [10, 10, 10], "w2": [10 * sign] * 3, "b2": 10 * sign}
            actual = self.analyze(data)
            expected = reference(data)
            self.assertEqual(actual["forward"]["logits"], [40 * sign])
            self.assertEqual(actual["forward"]["hidden_activations"], [[1, 1, 1]])
            for key in ("sample_losses", "hidden_slopes"):
                self.tree_close(actual["forward"][key], expected["forward"][key],
                                absolute=0, relative=2e-12)
            for key in ("logit_gradients", "w1", "b1", "w2", "b2", "inputs"):
                self.tree_close(actual["backward"][key], expected["backward"][key],
                                absolute=0, relative=2e-12)
                self.assertTrue(all(value != 0 for value in flatten(actual["backward"][key])))

    def test_maximum_shapes_values_and_step_budget_remain_finite(self):
        n, d, h = 32, 8, 8
        maximum = {"x": [[10] * d for _ in range(n)], "y": [0.25] * n,
                   "w1": [[10] * h for _ in range(d)], "b1": [10] * h,
                   "w2": [10] * h, "b2": 10}
        actual = self.analyze(maximum)
        self.validate(actual, maximum)
        self.assertEqual(actual["forward"]["logits"], [90] * n)
        self.assertEqual(actual["backward"]["w1"], [[0] * h for _ in range(d)])
        stationary = {"x": [[0] * d for _ in range(n)], "y": [0.5] * n,
                      "w1": [[0] * h for _ in range(d)], "b1": [0] * h,
                      "w2": [0] * h, "b2": 0}
        actual = self.analyze(stationary, "--steps", 5000, "--trace")
        self.validate(actual, stationary, steps=5000, trace=True)
        self.assertTrue(all(record["parameter_gradient_norm"] == 0 for record in actual["trace"]))

    def test_numeric_boundaries_and_representable_subnormals(self):
        data = {"x": [[-10]], "y": [1], "w1": [[10]], "b1": [-10], "w2": [-10], "b2": 10}
        self.validate(self.analyze(data, "--rate", 1e-6), data, rate=1e-6)
        for key in ("x", "y", *PARAMETERS):
            tiny = {"x": [[0]], "y": [0], "w1": [[0]], "b1": [0], "w2": [0], "b2": 0}
            indices = coordinates(tiny, key)[0]
            set_coordinate(tiny, key, indices, 1e-310)
            actual = self.analyze(tiny)
            if key == "x":
                self.assertEqual(actual["inputs"], [[1e-310]])
            elif key == "y":
                self.assertEqual(actual["targets"], [1e-310])
            else:
                self.assertEqual(get_coordinate(actual["parameters"], key, indices), 1e-310)
        text = "+0.0 -0 1.e+0 .0 0e99 -.0"
        actual = json.loads(self.run_program("--input", "-", "--json",
                                           input_text="1 1 1\n" + text).stdout)
        self.assertEqual(actual["parameters"]["w1"], [[1]])

    def test_invalid_cli_options(self):
        invalid = [
            ["--unknown"], ["--json", "--json"], ["--trace", "--trace"],
            ["--steps"], ["--rate"], ["--input"], ["--input", ""],
            ["--steps", "1", "--steps", "2"], ["--rate", ".1", "--rate", ".2"],
            ["--input", "-", "--input", "-"], ["--help", "--json"],
            ["--steps", "-1"], ["--steps", "+1"], ["--steps", "1.0"],
            ["--steps", "1e2"], ["--steps", "5001"], ["--steps", "99999999999999"],
        ]
        invalid += [["--rate", value] for value in
                    ("0", "-1", "0.0000009", "1.00001", "nan", "inf", "0x1p-1",
                     "1e999", "1e-999", "1e", "1x", "", ".", "1_0")]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                self.run_program(*arguments, input_text=serialize(DEMO), expected_code=1)

    def test_invalid_input_shapes_values_and_trailing_tokens(self):
        valid = "1 1 1 0 0.5 0 0 0 0"
        invalid = ["", "1", "1 1", "1 1 1", valid + " extra", valid[:-2],
                   "0 1 1", "33 1 1", "1 0 1", "1 9 1", "1 1 0", "1 1 9",
                   "-1 1 1", "+1 1 1", "1.0 1 1", "1 1e0 1", "99999999999999 1 1"]
        for index in range(3, 9):
            for token in ("nan", "inf", "-inf", "0x1p0", "1e999", "1e-999", "1e+", "--1", "1x"):
                tokens = valid.split()
                tokens[index] = token
                invalid.append(" ".join(tokens))
        for index in (3, 5, 6, 7, 8):
            for token in ("10.000001", "-10.000001"):
                tokens = valid.split()
                tokens[index] = token
                invalid.append(" ".join(tokens))
        for target in ("-0.0001", "1.00001"):
            tokens = valid.split()
            tokens[4] = target
            invalid.append(" ".join(tokens))
        for input_text in invalid:
            with self.subTest(input_text=input_text):
                self.run_program("--input", "-", "--json", input_text=input_text, expected_code=1)

    def test_file_stdin_help_and_human_output(self):
        path = self.directory / "network with spaces.txt"
        path.write_text(serialize(DEMO))
        file_result = self.run_program("--input", path, "--json").stdout
        stdin_result = self.run_program("--input", "-", "--json", input_text=serialize(DEMO)).stdout
        self.assertEqual(json.loads(file_result), json.loads(stdin_result))
        self.run_program("--input", self.directory / "missing.txt", expected_code=1)
        self.run_program("--input", self.directory, expected_code=1)
        help_output = self.run_program("--help").stdout
        self.assertIn("--steps", help_output)
        self.assertIn("--input", help_output)
        human = self.run_program().stdout
        self.assertTrue(human.strip())
        self.assertNotEqual(human.lstrip()[:1], "{")
        self.assertIn("0.763388895365999", human)
        traced = self.run_program("--steps", 2, "--trace").stdout
        self.assertNotEqual(human, traced)


if __name__ == "__main__":
    unittest.main(verbosity=2)
