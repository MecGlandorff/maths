#!/usr/bin/env python3
"""Verify PageRank through exact linear systems and observable CLI behavior."""

from fractions import Fraction
import itertools
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
WEB = ((0, 1, 1, 0), (0, 0, 1, 0), (1, 0, 0, 0), (0, 0, 0, 0))
CYCLE = tuple(tuple(int(j == (i + 1) % 4) for j in range(4)) for i in range(4))
SINKS = tuple((0, 0, 0, 0) for _ in range(4))
PRESETS = {"web": WEB, "cycle": CYCLE, "sinks": SINKS}
KEYS = {
    "nodes", "damping", "tolerance", "max_iterations", "personalization",
    "initial_scores", "dangling_nodes", "transition", "google_matrix", "scores",
    "ranking", "iterations", "residual_l1", "error_bound", "converged",
    "stop_reason", "history",
}


def rational(value):
    """Use the exact binary values accepted by the double-precision parser."""
    return Fraction(float(value))


def normalize(values):
    values = tuple(map(rational, values))
    total = sum(values)
    return tuple(value / total for value in values)


def serialize(matrix):
    return str(len(matrix)) + "\n" + "\n".join(" ".join(map(str, row)) for row in matrix) + "\n"


def transition(matrix, personalization=None):
    p = normalize(personalization if personalization is not None else [1] * len(matrix))
    return tuple(normalize(row) if any(map(float, row)) else p for row in matrix), p


def advance(scores, matrix, personalization, damping):
    return tuple(damping * sum(scores[i] * matrix[i][j] for i in range(len(scores)))
                 + (1 - damping) * personalization[j] for j in range(len(scores)))


def stationary(matrix, personalization=None, damping=0.85):
    """Solve (I-d*S^T)x=(1-d)p by exact rational Gaussian elimination."""
    matrix, p = transition(matrix, personalization)
    damping = rational(damping)
    n = len(matrix)
    augmented = [[Fraction(int(i == j)) - damping * matrix[j][i] for j in range(n)]
                 + [(1 - damping) * p[i]] for i in range(n)]
    for column in range(n):
        pivot = next(row for row in range(column, n) if augmented[row][column])
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            multiplier = augmented[row][column]
            augmented[row] = [a - multiplier * b for a, b in zip(augmented[row], augmented[column])]
    return tuple(row[-1] for row in augmented)


class PageRankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-pagerank-")
        cls.addClassCleanup(temporary.cleanup)
        cls.directory = Path(temporary.name)
        cls.binary = cls.directory / "pagerank"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "pagerank.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, input_text=None, expected_code=0):
        result = subprocess.run([str(self.binary), *map(str, arguments)], input=input_text,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        if expected_code in (0, 2):
            self.assertEqual(result.stderr, "")
        return result

    def close(self, actual, expected, relative=5e-12, absolute=1e-14):
        expected = float(expected)
        self.assertTrue(math.isfinite(actual), actual)
        bound = max(absolute, relative * abs(expected))
        self.assertLessEqual(abs(actual - expected), bound,
                             f"{actual!r} != {expected!r}; tolerance={bound!r}")

    def finite(self, value):
        if isinstance(value, dict):
            for item in value.values():
                self.finite(item)
        elif isinstance(value, list):
            for item in value:
                self.finite(item)
        elif not isinstance(value, (str, bool)) and value is not None:
            self.assertIn(type(value), (int, float))
            self.assertTrue(math.isfinite(value), value)

    def probability_vector(self, actual, expected=None):
        self.assertTrue(actual)
        self.close(math.fsum(actual), 1, relative=5e-13)
        for value in actual:
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1 + 1e-14)
        if expected is not None:
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected):
                self.close(a, b, relative=5e-14, absolute=0)

    def validate(self, matrix, output, damping=0.85, personalization=None, start=None,
                 tolerance=1e-10, max_iterations=1000, trace=False, expected_code=0):
        data = json.loads(output)
        self.assertEqual(set(data), KEYS)
        self.finite(data)
        n = len(matrix)
        self.assertIs(type(data["nodes"]), int)
        self.assertEqual(data["nodes"], n)
        self.close(data["damping"], rational(damping), relative=0, absolute=0)
        self.close(data["tolerance"], rational(tolerance), relative=0, absolute=0)
        self.assertEqual(data["max_iterations"], max_iterations)
        normalized, p = transition(matrix, personalization)
        initial = normalize(start if start is not None else [1] * n)
        self.probability_vector(data["personalization"], p)
        self.probability_vector(data["initial_scores"], initial)
        self.assertEqual(data["dangling_nodes"],
                         [i + 1 for i, row in enumerate(matrix) if not any(map(float, row))])
        d = rational(damping)
        google = tuple(tuple(d * normalized[i][j] + (1 - d) * p[j] for j in range(n))
                       for i in range(n))
        for label, exact in (("transition", normalized), ("google_matrix", google)):
            self.assertEqual(len(data[label]), n)
            for actual, expected in zip(data[label], exact):
                self.probability_vector(actual, expected)
        self.probability_vector(data["scores"])
        self.assertEqual(len(data["scores"]), n)
        self.assertIs(type(data["iterations"]), int)
        self.assertGreaterEqual(data["iterations"], 0)
        self.assertLessEqual(data["iterations"], max_iterations)
        exact_scores = tuple(map(rational, data["scores"]))
        next_scores = advance(exact_scores, normalized, p, d)
        residual = sum(abs(a - b) for a, b in zip(next_scores, exact_scores))
        self.close(data["residual_l1"], residual, absolute=4e-15)
        self.close(data["error_bound"], data["residual_l1"] / (1 - float(d)),
                   relative=5e-15, absolute=0)
        self.assertGreaterEqual(data["residual_l1"], 0)
        self.assertIs(type(data["converged"]), bool)
        self.assertEqual(data["converged"], data["error_bound"] <= float(tolerance))
        self.assertEqual(data["converged"], expected_code == 0)
        self.assertEqual(data["stop_reason"], "tolerance" if expected_code == 0 else "iteration_limit")
        if not data["converged"]:
            self.assertEqual(data["iterations"], max_iterations)
        reference = stationary(matrix, personalization, damping)
        true_error = sum(abs(a - b) for a, b in zip(exact_scores, reference))
        rounding_allowance = 64 * sys.float_info.epsilon / (1 - float(d))
        self.assertLessEqual(float(true_error), data["error_bound"] + rounding_allowance)
        self.assertEqual(len(data["ranking"]), n)
        expected_order = sorted(range(n), key=lambda i: (-data["scores"][i], i))
        self.assertEqual([entry["node"] for entry in data["ranking"]], [i + 1 for i in expected_order])
        for entry, index in zip(data["ranking"], expected_order):
            self.assertEqual(set(entry), {"node", "score"})
            self.assertIs(type(entry["node"]), int)
            self.assertEqual(entry["score"], data["scores"][index])
        history = data["history"]
        if trace:
            self.assertEqual(len(history), data["iterations"] + 1)
            previous = None
            for index, state in enumerate(history):
                self.assertEqual(set(state), {"iteration", "scores", "residual_l1", "error_bound"})
                self.assertEqual(state["iteration"], index)
                self.assertIs(type(state["iteration"]), int)
                self.assertEqual(len(state["scores"]), n)
                self.probability_vector(state["scores"])
                if previous is not None:
                    expected = [float(d) * math.fsum(float(normalized[i][j]) * previous[i]
                                                    for i in range(n)) + (1 - float(d)) * float(p[j])
                                for j in range(n)]
                    for actual, value in zip(state["scores"], expected):
                        self.close(actual, value, relative=3e-14, absolute=1e-16)
                advanced = [float(d) * math.fsum(float(normalized[i][j]) * state["scores"][i]
                                                for i in range(n)) + (1 - float(d)) * float(p[j])
                            for j in range(n)]
                expected_residual = math.fsum(abs(a - b) for a, b in zip(advanced, state["scores"]))
                self.close(state["residual_l1"], expected_residual, absolute=4e-15)
                self.close(state["error_bound"], state["residual_l1"] / (1 - float(d)),
                           relative=5e-15, absolute=0)
                if index < data["iterations"]:
                    self.assertGreater(state["error_bound"], float(tolerance))
                previous = state["scores"]
            self.assertEqual(history[0]["scores"], data["initial_scores"])
            self.assertEqual(history[-1]["scores"], data["scores"])
            self.assertEqual(history[-1]["residual_l1"], data["residual_l1"])
            self.assertEqual(history[-1]["error_bound"], data["error_bound"])
        else:
            self.assertEqual(history, [])
        return data

    def explore(self, matrix, damping=0.85, personalization=None, start=None,
                tolerance=1e-10, max_iterations=1000, trace=False, expected_code=0):
        arguments = ["--input", "-", "--damping", damping, "--tolerance", tolerance,
                     "--max-iterations", max_iterations, "--json"]
        if personalization is not None:
            arguments += ["--personalization", ",".join(map(str, personalization))]
        if start is not None:
            arguments += ["--start", ",".join(map(str, start))]
        if trace:
            arguments.append("--trace")
        result = self.run_program(*arguments, input_text=serialize(matrix), expected_code=expected_code)
        return self.validate(matrix, result.stdout, damping, personalization, start,
                             tolerance, max_iterations, trace, expected_code)

    def test_presets_and_default_graph(self):
        for name, matrix in PRESETS.items():
            with self.subTest(example=name):
                output = self.run_program("--example", name, "--json").stdout
                data = self.validate(matrix, output)
                self.assertEqual(data, self.explore(matrix))
        data = self.validate(WEB, self.run_program("--json").stdout)
        self.assertEqual(data["ranking"][0]["node"], 3)
        self.assertEqual(data["dangling_nodes"], [4])
        self.assertGreater(data["scores"][0], data["scores"][1])

    def test_weighted_orientation_and_exact_short_trajectory(self):
        matrix = ((0, 2, 1), (1, 0, 0), (0, 0, 0))
        p, start = (1, 2, 1), (1, 0, 0)
        data = self.explore(matrix, damping=0.5, personalization=p, start=start,
                            max_iterations=5, trace=True, expected_code=2)
        normalized, p_exact = transition(matrix, p)
        scores = normalize(start)
        for state in data["history"]:
            for actual, expected in zip(state["scores"], scores):
                self.close(actual, expected, relative=1e-14, absolute=0)
            next_scores = advance(scores, normalized, p_exact, Fraction(1, 2))
            residual = sum(abs(a - b) for a, b in zip(next_scores, scores))
            self.close(state["residual_l1"], residual, relative=2e-14)
            scores = next_scores
        self.close(data["history"][1]["scores"][1], Fraction(7, 12))

    def test_zero_damping_jumps_to_personalization(self):
        p = (0, 1, 2, 1)
        data = self.explore(WEB, damping=0, personalization=p, start=(1, 0, 0, 0), trace=True)
        self.assertEqual(data["iterations"], 1)
        self.assertEqual(data["scores"], [0, 0.25, 0.5, 0.25])
        self.assertEqual(data["error_bound"], 0)
        fixed = self.explore(WEB, damping=0, personalization=p, start=p, max_iterations=0, trace=True)
        self.assertEqual(fixed["iterations"], 0)

    def test_dangling_rows_follow_personalization(self):
        p = (2, 0, 1, 1)
        data = self.explore(SINKS, damping=0.875, personalization=p, trace=True)
        self.assertEqual(data["iterations"], 1)
        self.assertEqual(data["scores"], [0.5, 0, 0.25, 0.25])
        self.assertEqual(data["dangling_nodes"], [1, 2, 3, 4])
        personalized = self.explore(WEB, personalization=(0, 1, 0, 0), trace=True)
        self.assertEqual(personalized["transition"][3], [0, 1, 0, 0])
        absorbing = self.explore(WEB, personalization=(0, 0, 0, 1))
        self.assertGreater(absorbing["scores"][3], 1 - 1e-10)

    def test_singletons_self_loops_and_disconnected_zero_support(self):
        for matrix in (((0,),), ((1000000,),)):
            for damping in (0, 0.99):
                with self.subTest(matrix=matrix, damping=damping):
                    data = self.explore(matrix, damping=damping, max_iterations=0, trace=True)
                    self.assertEqual(data["scores"], [1])
                    self.assertEqual(data["iterations"], 0)
        identity = tuple(tuple(int(i == j) for j in range(3)) for i in range(3))
        self.explore(identity, personalization=(1, 2, 3), start=(1, 2, 3), max_iterations=0)
        matrix = ((0, 1, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 0))
        data = self.explore(matrix, personalization=(1, 1, 0, 0), start=(1, 0, 0, 0), trace=True)
        self.assertEqual(data["scores"][2:], [0, 0])
        for state in data["history"]:
            self.assertEqual(state["scores"][2:], [0, 0])

    def test_cycle_modes_and_slow_convergence(self):
        data = self.explore(CYCLE, damping=0.5, start=(1, 0, 0, 0),
                            max_iterations=8, trace=True, expected_code=2)
        for state in data["history"]:
            iteration = state["iteration"]
            expected = [0.25 + 0.5 ** iteration * (int(j == iteration % 4) - 0.25) for j in range(4)]
            self.assertEqual(state["scores"], expected)
            self.close(state["residual_l1"], 1.75 * 0.5 ** iteration, relative=0, absolute=0)
        short = self.explore(CYCLE, damping=0.99, start=(1, 0, 0, 0),
                             max_iterations=16, trace=True, expected_code=2)
        self.assertEqual(short["iterations"], 16)
        long = self.explore(CYCLE, damping=0.99, start=(1, 0, 0, 0),
                            max_iterations=10000, tolerance=1e-12)
        self.assertGreater(long["iterations"], 1000)
        for score in long["scores"]:
            self.close(score, 0.25, absolute=1e-12)

    def test_initial_state_and_iteration_budget_boundaries(self):
        fixed = self.explore(CYCLE, max_iterations=0, trace=True)
        self.assertEqual(fixed["iterations"], 0)
        self.assertEqual([row["node"] for row in fixed["ranking"]], [1, 2, 3, 4])
        limited = self.explore(WEB, max_iterations=0, trace=True, expected_code=2)
        self.assertEqual(limited["scores"], [0.25] * 4)
        self.explore(WEB, damping=0, personalization=(1, 0, 0, 0), max_iterations=1)
        for budget, code in ((11, 2), (12, 0), (20, 0)):
            result = self.explore(CYCLE, damping=0.5, start=(1, 0, 0, 0), tolerance=0.001,
                                  max_iterations=budget, trace=True, expected_code=code)
            self.assertEqual(result["iterations"], min(budget, 12))

    def test_residual_bound_is_for_the_current_reported_state(self):
        for budget in (0, 1, 2, 5):
            data = self.explore(WEB, damping=0.75, start=(0, 1, 0, 0),
                                max_iterations=budget, trace=True, expected_code=2)
            exact = stationary(WEB, damping=0.75)
            actual_error = sum(abs(rational(a) - b) for a, b in zip(data["scores"], exact))
            self.assertLessEqual(actual_error, rational(data["error_bound"]) + Fraction(1, 10 ** 14))
            if budget:
                previous = data["history"][-2]["error_bound"]
                self.assertLess(data["error_bound"], previous)

    def test_weight_scaling_permutations_and_start_invariance(self):
        matrix = ((0, 3, 1), (2, 1, 0), (0, 0, 0))
        p, start = (1, 2, 3), (3, 1, 2)
        base = self.explore(matrix, personalization=p, start=start)
        rescaled = tuple(tuple(value * scale for value in row) for row, scale in zip(matrix, (8, 0.5, 2)))
        scaled = self.explore(rescaled, personalization=(8, 16, 24), start=(6, 2, 4))
        for a, b in zip(base["scores"], scaled["scores"]):
            self.close(a, b, relative=1e-14)
        permutation = (2, 0, 1)
        alternate = tuple(tuple(matrix[i][j] for j in permutation) for i in permutation)
        permuted = self.explore(alternate, personalization=tuple(p[i] for i in permutation),
                                start=tuple(start[i] for i in permutation))
        for new, old in enumerate(permutation):
            self.close(permuted["scores"][new], base["scores"][old], relative=1e-13)
        other_start = self.explore(matrix, personalization=p, start=(0, 0, 1))
        self.assertLessEqual(math.fsum(abs(a - b) for a, b in zip(base["scores"], other_start["scores"])),
                             base["error_bound"] + other_start["error_bound"] + 1e-13)

    def test_small_and_seeded_graphs_match_exact_linear_systems(self):
        for edges in itertools.product((0, 1), repeat=4):
            matrix = (edges[:2], edges[2:])
            with self.subTest(edges=edges):
                self.explore(matrix, damping=0.5, personalization=(1, 3), trace=True)
        generator = random.Random(16429)
        for case in range(16):
            n = generator.randint(2, 7)
            matrix = tuple(tuple(generator.choice((0, 0, 1, 2, 4)) for _ in range(n)) for _ in range(n))
            p = [generator.randint(0, 4) for _ in range(n)]
            p[0] = 1
            with self.subTest(case=case):
                self.explore(matrix, damping=generator.choice((0.25, 0.5, 0.875)),
                             personalization=p, trace=True)

    def test_maximum_dimensions_and_numeric_boundaries(self):
        # A positive representable subnormal is still a valid damping value.
        # It remains visible after one update even though 1-d rounds to one.
        subnormal = self.explore(((1, 0), (0, 1)), damping="1e-310",
                                 personalization=(1, 0), start=(0, 1), trace=True)
        self.assertEqual(subnormal["iterations"], 1)
        self.assertGreater(subnormal["damping"], 0)
        self.assertEqual(subnormal["scores"][1], float("1e-310"))
        n = 16
        matrix = tuple(tuple(1000000 if j == (i + 1) % n else 1e-12 if j == i else 0
                             for j in range(n)) for i in range(n))
        p = [1000000] + [1e-12] * (n - 1)
        self.explore(matrix, damping=0.99, personalization=p, start=[1] + [0] * (n - 1),
                     max_iterations=10000, tolerance=1e-12)
        zero = tuple(tuple(0 for _ in range(n)) for _ in range(n))
        tiny = self.explore(zero, personalization=p)
        self.assertGreater(tiny["scores"][-1], 0)
        self.close(tiny["scores"][-1], Fraction(1, 10 ** 18 + 15), relative=5e-14, absolute=0)
        self.explore((("-0",),), damping=0, personalization=("+1e-12",), start=("1e6",))

    def test_file_input_help_and_terminal_output(self):
        path = self.directory / "graph with spaces.txt"
        path.write_text(serialize(WEB), encoding="utf-8")
        result = self.run_program("--input", path, "--json")
        self.assertEqual(self.validate(WEB, result.stdout), self.explore(WEB))
        help_text = self.run_program("--help").stdout
        for option in ("--input", "--example", "--damping", "--personalization", "--start",
                       "--tolerance", "--max-iterations", "--trace", "--json"):
            self.assertIn(option, help_text)
        arguments = ["--input", path, "--damping", "0.875", "--personalization", "1,3,2,4",
                     "--start", "4,1,1,2", "--tolerance", "1e-12", "--max-iterations", "5", "--trace"]
        output = self.run_program(*arguments, "--json", expected_code=2).stdout
        data = self.validate(WEB, output, damping=0.875, personalization=(1, 3, 2, 4),
                             start=(4, 1, 1, 2), tolerance=1e-12, max_iterations=5,
                             trace=True, expected_code=2)
        lines = self.run_program(*arguments, expected_code=2).stdout.splitlines()
        rank_start = lines.index("node  score") + 1
        for line, entry in zip(lines[rank_start:rank_start + 4], data["ranking"]):
            node, score = line.split()
            self.assertEqual(int(node), entry["node"])
            self.assertEqual(float(score), entry["score"])
        trace_start = lines.index("iteration  residual_l1  error_bound  scores") + 1
        trace_lines = lines[trace_start:trace_start + len(data["history"])]
        self.assertEqual(len(trace_lines), len(data["history"]))
        for line, state in zip(trace_lines, data["history"]):
            iteration, residual, bound, scores = line.split(maxsplit=3)
            self.assertEqual(int(iteration), state["iteration"])
            self.assertEqual(float(residual), state["residual_l1"])
            self.assertEqual(float(bound), state["error_bound"])
            self.assertEqual(json.loads(scores), state["scores"])

    def test_invalid_options(self):
        cases = [("--unknown",), ("web",), ("--example", "unknown"),
                 ("--input", ""), ("--input", self.directory / "missing.txt"),
                 ("--json", "--json"), ("--trace", "--trace"), ("--help", "--json"),
                 ("--example", "web", "--input", "-")]
        for flag, value in (("--example", "web"), ("--input", "-"), ("--damping", "0.5"),
                            ("--tolerance", "1e-8"), ("--max-iterations", "2"),
                            ("--personalization", "1,1,1,1"), ("--start", "1,1,1,1")):
            cases.extend(((flag,), (flag, value, flag, value)))
        for value in ("-1", "1", "0.990001", "nan", "inf", "0x1p0", "1_0", "1e999", "1e-999"):
            cases.append(("--damping", value))
        for value in ("0", "-1", "1e-13", "0.0011", "nan", "inf"):
            cases.append(("--tolerance", value))
        for value in ("-1", "10001", "1.5", "1e2", "x", "99999999999999999999"):
            cases.append(("--max-iterations", value))
        for flag in ("--personalization", "--start"):
            for value in ("", ",", "1,1,1", "1,1,1,1,1", "0,0,0,0", "1,,1,1", "1,1,1,",
                          "-1,1,1,1", "1e-13,1,1,1", "1000001,1,1,1", "nan,1,1,1", "inf,1,1,1"):
                cases.append((flag, value))
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, input_text=serialize(WEB), expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())

    def test_invalid_graph_input(self):
        cases = ["", "0\n", "17\n", "-1\n", "1.5\n", "one\n", "1\n", "2\n0 1 0\n",
                 "1\n1 extra\n", "1\n1 2\n"]
        for value in ("-1", "-1e-12", "1e-13", "1000001", "nan", "NaN", "inf", "-Infinity",
                      "0x1p0", "1_0", "1e999", "1e-999", ".", "1e"):
            cases.append(f"1\n{value}\n")
        for input_text in cases:
            with self.subTest(input_text=input_text):
                result = self.run_program("--input", "-", "--json", input_text=input_text, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.strip())


if __name__ == "__main__":
    unittest.main()
