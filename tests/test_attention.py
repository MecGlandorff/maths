#!/usr/bin/env python3
"""Check attention with high-precision forward values and independent derivatives."""

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
DEMO_Q = ((1, 0), (0, 1), (1, 1))
DEMO_K = ((1, 0), (0, 1), (-1, 1))
DEMO_V = ((1, 0), (0, 2), (-1, -1))
DEMO_G = ((1, 0.5), (-0.5, 1), (0.25, -1))
JSON_KEYS = {
    "query_count", "key_count", "key_dimensions", "value_dimensions", "temperature",
    "causal", "query", "key", "value", "scores", "weights", "output", "entropy", "gradients",
}


def decimal(value):
    return Decimal.from_float(value) if isinstance(value, float) else Decimal(value)


def decimal_forward(query, key, value, temperature, causal):
    """Evaluate the defining softmax expression with 80-digit Decimal arithmetic."""
    with localcontext() as context:
        context.prec = 80
        q, k, v = ([[decimal(item) for item in row] for row in matrix]
                   for matrix in (query, key, value))
        divisor = Decimal(len(q[0])).sqrt() * decimal(temperature)
        scores = [[sum(a * b for a, b in zip(row, key_row)) / divisor
                   for key_row in k] for row in q]
        weights, output, entropy = [], [], []
        for index, row in enumerate(scores):
            visible = index + 1 if causal else len(k)
            maximum = max(row[:visible])
            terms = [(score - maximum).exp() if column < visible else Decimal(0)
                     for column, score in enumerate(row)]
            denominator = sum(terms)
            probabilities = [term / denominator for term in terms]
            weights.append(probabilities)
            output.append([sum(probabilities[j] * v[j][column] for j in range(len(k)))
                           for column in range(len(v[0]))])
            entropy.append(-sum(p * p.ln() for p in probabilities if p))
        return scores, weights, output, entropy


def objective(query, key, value, upstream, temperature, causal):
    with localcontext() as context:
        context.prec = 80
        output = decimal_forward(query, key, value, temperature, causal)[2]
        return sum(item * decimal(gradient) for row, g in zip(output, upstream)
                   for item, gradient in zip(row, g))


def serialize(query, key, value, upstream=None):
    matrices = (query, key, value) + ((upstream,) if upstream is not None else ())
    header = f"{len(query)} {len(key)} {len(query[0])} {len(value[0])}\n"
    return header + "\n".join(" ".join(str(item) for item in row)
                               for matrix in matrices for row in matrix) + "\n"


def magnitude(matrix):
    return max(abs(value) for row in matrix for value in row)


class AttentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-attention-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "attention"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "attention.cpp"), "-o", str(cls.binary)]
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

    def close(self, actual, expected, scale=0, tolerance=3e-12):
        expected = float(expected)
        self.assertTrue(math.isfinite(actual), actual)
        allowed = tolerance * max(abs(expected), abs(scale))
        self.assertLessEqual(abs(actual - expected), allowed,
                             f"{actual!r} != {expected!r} (tolerance {allowed!r})")

    def matrix_close(self, actual, expected, scale=0, tolerance=3e-12):
        self.assertEqual(len(actual), len(expected))
        for actual_row, expected_row in zip(actual, expected):
            self.assertEqual(len(actual_row), len(expected_row))
            for a, b in zip(actual_row, expected_row):
                self.close(a, b, scale, tolerance)

    def assert_finite_json(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.assert_finite_json(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_finite_json(item)
        elif value is not None:
            self.assertIn(type(value), (int, float, bool))
            self.assertTrue(math.isfinite(value), value)

    def validate(self, result, query, key, value, upstream=None, temperature=1, causal=False):
        data = json.loads(result.stdout)
        self.assertEqual(set(data), JSON_KEYS)
        self.assert_finite_json(data)
        m, n, dk, dv = len(query), len(key), len(query[0]), len(value[0])
        for label, expected in (("query_count", m), ("key_count", n),
                                ("key_dimensions", dk), ("value_dimensions", dv)):
            self.assertIs(type(data[label]), int)
            self.assertEqual(data[label], expected)
        self.assertIs(type(data["causal"]), bool)
        self.assertEqual(data["causal"], causal)
        self.close(data["temperature"], temperature)
        for label, expected in (("query", query), ("key", key), ("value", value)):
            self.assertEqual(data[label], [list(row) for row in expected])
        scores, weights, output, entropy = decimal_forward(query, key, value, temperature, causal)
        score_scale = float(max(abs(item) for row in scores for item in row))
        self.matrix_close(data["scores"], scores, score_scale, 3e-14)
        self.matrix_close(data["weights"], weights, 1)
        self.matrix_close(data["output"], output, magnitude(value))
        self.assertEqual(len(data["entropy"]), m)
        for i in range(m):
            visible = i + 1 if causal else n
            self.close(math.fsum(data["weights"][i]), 1, tolerance=3e-14)
            for j, probability in enumerate(data["weights"][i]):
                self.assertGreaterEqual(probability, 0)
                self.assertLessEqual(probability, 1)
                if j >= visible:
                    self.assertEqual(probability, 0)
            self.close(data["entropy"][i], entropy[i], 1)
            self.assertGreaterEqual(data["entropy"][i], -3e-14)
            self.assertLessEqual(data["entropy"][i], math.log(visible) + 3e-14)
            for column in range(dv):
                entries = [row[column] for row in value[:visible]]
                slack = 3e-12 * max(map(abs, entries))
                self.assertGreaterEqual(data["output"][i][column], min(entries) - slack)
                self.assertLessEqual(data["output"][i][column], max(entries) + slack)
        if upstream is None:
            self.assertIsNone(data["gradients"])
        else:
            gradients = data["gradients"]
            self.assertEqual(set(gradients), {"upstream", "objective", "query", "key", "value"})
            self.assertEqual(gradients["upstream"], [list(row) for row in upstream])
            loss = objective(query, key, value, upstream, temperature, causal)
            loss_scale = m * dv * magnitude(value) * magnitude(upstream)
            self.close(gradients["objective"], loss, loss_scale)
            for label, rows, columns in (("query", m, dk), ("key", n, dk), ("value", n, dv)):
                self.assertEqual(len(gradients[label]), rows)
                self.assertTrue(all(len(row) == columns for row in gradients[label]))
        return data

    def attention(self, query, key, value, upstream=None, temperature=1, causal=False):
        arguments = ["--input", "-", "--temperature", temperature, "--json"]
        if causal:
            arguments.append("--causal")
        if upstream is not None:
            arguments.append("--backward")
        result = self.run_program(*arguments, input_text=serialize(query, key, value, upstream))
        return self.validate(result, query, key, value, upstream, temperature, causal)

    def test_defaults_and_equivalent_stdin(self):
        for causal in (False, True):
            for backward in (False, True):
                with self.subTest(causal=causal, backward=backward):
                    args = ["--json"]
                    if causal:
                        args.append("--causal")
                    if backward:
                        args.append("--backward")
                    upstream = DEMO_G if backward else None
                    result = self.run_program(*args)
                    default = self.validate(result, DEMO_Q, DEMO_K, DEMO_V, upstream, causal=causal)
                    supplied = self.attention(DEMO_Q, DEMO_K, DEMO_V, upstream, causal=causal)
                    self.assertEqual(default, supplied)
        human = self.run_program("--backward")
        self.assertTrue(human.stdout.strip())
        self.assertFalse(human.stdout.lstrip().startswith("{"))

    def test_one_key_and_analytic_uniform_gradients(self):
        query, key, value = ((2, -1), (-3, 4)), ((1, 2),), ((5, -2),)
        upstream = ((1, 3), (-2, 4))
        data = self.attention(query, key, value, upstream, temperature=2.3)
        self.assertEqual(data["weights"], [[1], [1]])
        self.assertEqual(data["output"], [[5, -2], [5, -2]])
        self.assertEqual(data["entropy"], [0, 0])
        self.assertEqual(data["gradients"]["query"], [[0, 0], [0, 0]])
        self.assertEqual(data["gradients"]["key"], [[0, 0]])
        self.assertEqual(data["gradients"]["value"], [[-1, 7]])
        uniform = self.attention(((0,),), ((-1,), (1,)), ((2,), (6,)), ((3,),), temperature=2)
        self.matrix_close(uniform["gradients"]["query"], [[3]])
        self.assertEqual(uniform["gradients"]["key"], [[0], [0]])
        self.matrix_close(uniform["gradients"]["value"], [[1.5], [1.5]])
        self.close(uniform["gradients"]["objective"], 12)

    def test_zero_queries_tied_keys_and_temperature(self):
        query = ((0, 0), (0, 0))
        key = ((1, -2), (3, 4), (-5, 6))
        value = ((1, 2), (3, -4), (5, 8))
        for temperature in (0.001, 1, 1000):
            data = self.attention(query, key, value, temperature=temperature)
            self.matrix_close(data["weights"], [[1 / 3] * 3] * 2)
            self.matrix_close(data["output"], [[3, 2]] * 2)
        self.attention(((1, -2),), ((3, 4),) * 16, tuple((index,) for index in range(16)))
        entropies = []
        for temperature in (0.001, 0.1, 1, 10, 1000):
            data = self.attention(((1,),), ((0,), (1,), (2,)), ((-1,), (2,), (4,)),
                                  temperature=temperature)
            entropies.append(data["entropy"][0])
        self.assertEqual(entropies, sorted(entropies))
        base = self.attention(DEMO_Q, DEMO_K, DEMO_V, temperature=1.5)
        scaled = self.attention(tuple(tuple(2 * item for item in row) for row in DEMO_Q),
                                DEMO_K, DEMO_V, temperature=3)
        self.matrix_close(scaled["weights"], base["weights"], 1)

    def test_extreme_logits_and_visible_causal_maximum(self):
        value = ((1, -2), (5, 6), (-3, 4))
        for key, selected in ((((1e6,), (-1e6,), (0,)), 0),
                              (((-1e6,), (-999999,), (-999998,)), 2)):
            data = self.attention(((1e6,),), key, value, temperature=0.001)
            self.assertEqual(data["weights"], [[int(index == selected) for index in range(3)]])
            self.assertEqual(data["output"], [list(value[selected])])
            self.assertEqual(data["entropy"], [0])
        query, key = ((1,),) * 3, ((0,), (1e6,), (1e6,))
        upstream = ((1, -2), (0, 0), (0, 0))
        data = self.attention(query, key, value, upstream, causal=True)
        self.assertEqual(data["weights"][0], [1, 0, 0])
        self.assertEqual(data["weights"][1], [0, 1, 0])
        self.assertEqual(data["weights"][2], [0, 0.5, 0.5])
        self.assertEqual(data["gradients"]["query"], [[0], [0], [0]])
        self.assertEqual(data["gradients"]["key"], [[0], [0], [0]])
        self.assertEqual(data["gradients"]["value"], [[1, -2], [0, 0], [0, 0]])
        changed = self.attention(query, ((0,), (1e6,), (-1e6,)),
                                 (value[0], value[1], (1e6, -1e6)), causal=True)
        self.assertEqual(changed["output"][:2], data["output"][:2])

    def test_independent_finite_difference_gradients(self):
        cases = (
            (((0.2, -0.7), (1.1, 0.3)),
             ((-0.4, 0.8), (0.9, -0.2), (0.3, 0.6)),
             ((1.2, -0.5), (-0.7, 0.9), (0.4, 1.1)),
             ((0.3, -0.8), (1.2, 0.5)), 0.7, False),
            (((0.4, -0.6), (0.2, 0.8), (-0.9, 0.3)),
             ((0.1, 0.7), (-0.5, 0.2), (0.6, -0.4)),
             ((0.8, -0.3), (-0.2, 1.1), (0.7, 0.5)),
             ((-0.4, 0.9), (0.6, -0.2), (1.2, 0.3)), 1.7, True),
        )
        for query, key, value, upstream, temperature, causal in cases:
            data = self.attention(query, key, value, upstream, temperature, causal)
            with localcontext() as context:
                context.prec = 80
                step = Decimal("0.001")
                matrices = [[[decimal(item) for item in row] for row in matrix]
                            for matrix in (query, key, value)]
                for variable, label in enumerate(("query", "key", "value")):
                    for row in range(len(matrices[variable])):
                        for column in range(len(matrices[variable][row])):
                            with self.subTest(causal=causal, variable=label, row=row, column=column):
                                original = matrices[variable][row][column]
                                losses = []
                                for offset in (-2, -1, 1, 2):
                                    matrices[variable][row][column] = original + offset * step
                                    losses.append(objective(*matrices, upstream, temperature, causal))
                                matrices[variable][row][column] = original
                                derivative = (losses[0] - 8 * losses[1] + 8 * losses[2] - losses[3]) / (12 * step)
                                self.close(data["gradients"][label][row][column], derivative, 1, 2e-8)

    def test_key_permutation_and_common_shift(self):
        base = self.attention(DEMO_Q, DEMO_K, DEMO_V, DEMO_G, temperature=0.8)
        order = (2, 0, 1)
        permuted = self.attention(DEMO_Q, tuple(DEMO_K[index] for index in order),
                                  tuple(DEMO_V[index] for index in order), DEMO_G, temperature=0.8)
        self.matrix_close(permuted["output"], base["output"], 2)
        self.matrix_close(permuted["weights"], [[row[index] for index in order] for row in base["weights"]], 1)
        self.matrix_close(permuted["gradients"]["query"], base["gradients"]["query"], 2)
        for label in ("key", "value"):
            self.matrix_close(permuted["gradients"][label],
                              [base["gradients"][label][index] for index in order], 2)
        shifted_keys = tuple((row[0] + 5, row[1] - 7) for row in DEMO_K)
        shifted = self.attention(DEMO_Q, shifted_keys, DEMO_V, DEMO_G, temperature=0.8)
        self.matrix_close(shifted["weights"], base["weights"], 1)
        self.matrix_close(shifted["output"], base["output"], 2)
        for label in ("query", "key", "value"):
            self.matrix_close(shifted["gradients"][label], base["gradients"][label], 10)

    def test_value_affinity_and_upstream_linearity(self):
        base = self.attention(DEMO_Q, DEMO_K, DEMO_V, DEMO_G, temperature=1.3, causal=True)
        transformed_v = tuple((-2 * row[0] + 3, -2 * row[1] - 4) for row in DEMO_V)
        transformed = self.attention(DEMO_Q, DEMO_K, transformed_v, DEMO_G,
                                     temperature=1.3, causal=True)
        self.matrix_close(transformed["weights"], base["weights"], 1)
        expected = [[-2 * row[0] + 3, -2 * row[1] - 4] for row in base["output"]]
        self.matrix_close(transformed["output"], expected, 10)
        for label in ("query", "key"):
            self.matrix_close(transformed["gradients"][label],
                              [[-2 * item for item in row] for row in base["gradients"][label]], 10)
        self.matrix_close(transformed["gradients"]["value"], base["gradients"]["value"], 2)
        for multiplier in (0, -3):
            upstream = tuple(tuple(multiplier * item for item in row) for row in DEMO_G)
            result = self.attention(DEMO_Q, DEMO_K, DEMO_V, upstream, temperature=1.3, causal=True)
            for label in ("query", "key", "value"):
                expected = [[multiplier * item for item in row] for row in base["gradients"][label]]
                self.matrix_close(result["gradients"][label], expected, abs(multiplier) * 10)

    def test_constant_values_remove_query_and_key_gradients(self):
        values = ((1.5, -2),) * 3
        for causal in (False, True):
            data = self.attention(DEMO_Q, DEMO_K, values, DEMO_G, temperature=0.6, causal=causal)
            self.matrix_close(data["output"], values, 2)
            self.matrix_close(data["gradients"]["query"], [[0, 0]] * 3, 10)
            self.matrix_close(data["gradients"]["key"], [[0, 0]] * 3, 10)

    def test_seeded_shapes_and_numeric_boundaries(self):
        rng = random.Random(20261013)
        for m, n, dk, dv, causal in ((1, 16, 1, 8, False), (16, 1, 8, 1, False),
                                    (16, 16, 8, 8, False), (16, 16, 8, 8, True),
                                    (5, 7, 3, 4, False), (1, 1, 1, 1, True)):
            with self.subTest(m=m, n=n, dk=dk, dv=dv, causal=causal):
                matrix = lambda rows, columns: tuple(tuple(rng.randrange(-4, 5) / 4
                                                           for _ in range(columns)) for _ in range(rows))
                self.attention(matrix(m, dk), matrix(n, dk), matrix(n, dv), matrix(m, dv),
                               temperature=0.9, causal=causal)
        for bound in (1e-100, 1e6):
            self.attention(((bound,),), ((-bound,), (bound,)), ((bound,), (-bound,)),
                           ((bound,),), temperature=0.001)

    def test_files_flag_order_decimal_syntax_and_help(self):
        text = " 1\t2 1 1\n+.5\n-1. +1E0\n-0.0 +2.\n-3e-1 \n"
        query, key, value, upstream = ((0.5,),), ((-1,), (1,)), ((0,), (2,)), ((-0.3,),)
        path = self.directory / "input with spaces.txt"
        path.write_text(text, encoding="utf-8")
        for arguments in (("--backward", "--json", "--temperature", "+1e0", "--input", str(path)),
                          ("--input", "-", "--temperature", 1, "--json", "--backward")):
            result = self.run_program(*arguments, input_text=text)
            self.validate(result, query, key, value, upstream)
        help_result = self.run_program("--help")
        for flag in ("--input", "--temperature", "--causal", "--backward", "--json"):
            self.assertIn(flag, help_result.stdout)

    def test_human_output_includes_all_sixteen_rows_and_gradients(self):
        query = key = ((0,),) * 16
        value = tuple((index,) for index in range(16))
        upstream = ((1,),) * 16
        result = self.run_program("--input", "-", "--backward",
                                  input_text=serialize(query, key, value, upstream))
        lines = result.stdout.splitlines()
        for label, expected in (
            ("Weights (each row sums to 1)", [[1 / 16] * 16] * 16),
            ("Output = weights * V", [[7.5]] * 16),
            ("dL/dQ", [[0]] * 16), ("dL/dK", [[0]] * 16), ("dL/dV", [[1]] * 16),
        ):
            with self.subTest(label=label):
                self.assertEqual(lines.count(label + ":"), 1)
                start = lines.index(label + ":") + 1
                actual = [json.loads(line) for line in lines[start:start + 16]]
                self.assertEqual(actual, expected)

        precise = 1.2345678901234567
        result = self.run_program("--input", "-", "--backward", "--temperature", precise,
                                  input_text=serialize(((0,),), ((0,),), ((precise,),), ((precise,),)))
        lines = result.stdout.splitlines()
        for label in ("V (values)", "Output = weights * V", "G (upstream derivative)", "dL/dV"):
            with self.subTest(label=label, precision=True):
                start = lines.index(label + ":") + 1
                self.assertEqual(json.loads(lines[start]), [precise])
        for label, expected in (("Temperature", precise),
                                ("Scalar probe L = sum(O * G)", precise * precise)):
            with self.subTest(label=label, precision=True):
                line, = (line for line in lines if line.startswith(label + ": "))
                self.assertEqual(float(line.split(": ", 1)[1]), expected)

    def test_invalid_flags_dimensions_and_values(self):
        invalid_flags = [
            ("--unknown",), ("extra",), ("--input",), ("--temperature",),
            ("--help", "--json"), ("--json", "--help"), ("--help", "--help"),
            ("--json", "--json"), ("--causal", "--causal"), ("--backward", "--backward"),
            ("--temperature", 1, "--temperature", 2), ("--input", "-", "--input", "-"),
            ("--input", ""), ("--input", str(self.directory / "does-not-exist")),
        ]
        invalid_flags.extend(("--temperature", value) for value in
                             ("", "0", "-0", "-1", "0.0009", "1001", "nan", "inf",
                              "0x1p0", "1x", " 1", "1 ", "1e999", "1e-999"))
        for arguments in invalid_flags:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
        invalid_inputs = ["", "1", "1 1 1", "1 1 1 1", "1 1 1 1 1 2", "1 1 1 1 1 2 3 4",
                          "1 1 1 1 1 2 3 extra", "+1 1 1 1 1 2 3", "-0 1 1 1 1 2 3",
                          "1.0 1 1 1 1 2 3", "1 1x 1 1 1 2 3", "999999999999999999999 1 1 1"]
        for column, upper in enumerate((16, 16, 8, 8)):
            for bad in (0, upper + 1):
                dimensions = [1, 1, 1, 1]
                dimensions[column] = bad
                invalid_inputs.append(" ".join(map(str, dimensions)) + " 1 2 3")
        invalid_tokens = ("nan", "NaN", "+nan", "nan(0)", "inf", "-inf", "Infinity",
                          "0x1p0", "0X1.0P+2", "1_000", "1,5", "--1", "+", "-", ".",
                          "1e", "1e+", "1e-", "1e1x", "1.2.3", "1e999", "1e-999",
                          "1e-101", "9e-101", "1000001", "-1000001")
        invalid_inputs.extend(f"1 1 1 1 1 2 {token}" for token in invalid_tokens)
        for text in invalid_inputs:
            with self.subTest(input_text=text):
                result = self.run_program("--input", "-", "--json", input_text=text, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)
        for arguments, text in (
            (("--backward",), "1 1 1 1 1 2 3"),
            (("--backward",), "1 1 1 1 1 2 3 4 5"),
            (("--backward",), "1 1 1 1 1 2 3 nan"),
            (("--causal",), "1 2 1 1 1 2 3 4 5"),
        ):
            result = self.run_program("--input", "-", "--json", *arguments,
                                      input_text=text, expected_code=1)
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr)


if __name__ == "__main__":
    unittest.main()
