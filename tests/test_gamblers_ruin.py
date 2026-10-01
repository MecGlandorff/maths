#!/usr/bin/env python3
"""Compile and check the public gambler's ruin CLI using only the standard library."""

from fractions import Fraction
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def absorbing_chain(target, win_percent):
    """Solve the finite Markov chain exactly, independently of the closed forms."""
    p = Fraction(win_percent, 100)
    q = 1 - p
    count = target - 1
    diagonal = [Fraction(1) for _ in range(count)]
    probability_rhs = [Fraction(0) for _ in range(count)]
    probability_rhs[-1] = p  # P(target)=1; P(0)=0.
    duration_rhs = [Fraction(1) for _ in range(count)]  # One step per update.

    # Equations: u(i) - q*u(i-1) - p*u(i+1) = rhs(i).
    for row in range(1, count):
        factor = -q / diagonal[row - 1]
        diagonal[row] -= factor * -p
        probability_rhs[row] -= factor * probability_rhs[row - 1]
        duration_rhs[row] -= factor * duration_rhs[row - 1]

    def back_substitute(rhs):
        solution = [Fraction(0) for _ in range(count)]
        for row in range(count - 1, -1, -1):
            next_value = solution[row + 1] if row + 1 < count else 0
            solution[row] = (rhs[row] + p * next_value) / diagonal[row]
        return solution

    probabilities = [Fraction(0)] + back_substitute(probability_rhs) + [Fraction(1)]
    durations = [Fraction(0)] + back_substitute(duration_rhs) + [Fraction(0)]
    return probabilities, durations


class GamblersRuinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-gamblers-ruin-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "gamblers_ruin"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "gamblers_ruin.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, expected_codes=(0,)):
        result = subprocess.run(
            [str(self.binary), *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertIn(result.returncode, expected_codes, result.stdout + result.stderr)
        return result

    def value(self, output, label):
        match = re.search(rf"^{re.escape(label)}: (\S+)$", output, re.MULTILINE)
        self.assertIsNotNone(match, output)
        return float(match.group(1))

    def counts(self, output):
        return tuple(int(self.value(output, label))
                     for label in ("Successes", "Ruins", "Unresolved"))

    def path(self, output):
        graph = output.split("Sample path", 1)[1]
        rows = re.findall(r"^\s*(\d+) \|([ *]+)\|", graph, re.MULTILINE)
        self.assertTrue(rows, graph)
        widths = {len(row) for _, row in rows}
        self.assertEqual(len(widths), 1)
        positions = []
        for column in range(widths.pop()):
            stars = [int(capital) for capital, row in rows if row[column] == "*"]
            self.assertEqual(len(stars), 1)
            positions.append(stars[0])
        return positions

    def test_formulas_against_exact_absorbing_chain(self):
        for target in (2, 3, 7, 20, 40):
            for win_percent in (0, 1, 25, 49, 50, 51, 75, 99, 100):
                with self.subTest(target=target, win_percent=win_percent):
                    result = self.run_program(
                        target // 2, target, win_percent, 1, 42, 1,
                        expected_codes=(0, 2),
                    )
                    rows = re.findall(
                        r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+\[",
                        result.stdout, re.MULTILINE,
                    )
                    self.assertEqual([int(row[0]) for row in rows], list(range(target + 1)))
                    probabilities, durations = absorbing_chain(target, win_percent)
                    for capital, probability, duration in rows:
                        index = int(capital)
                        self.assertTrue(math.isclose(
                            float(probability), float(probabilities[index]),
                            rel_tol=5.1e-9, abs_tol=1e-100,
                        ), (target, win_percent, index, probability, probabilities[index]))
                        self.assertAlmostEqual(
                            float(duration), float(durations[index]), delta=5.1e-7,
                        )

    def test_default_run_and_truncated_preview(self):
        output = self.run_program().stdout
        self.assertEqual(self.value(output, "Theoretical success probability"), 0.5)
        self.assertEqual(self.value(output, "Theoretical expected steps"), 100)
        successes, ruins, unresolved = self.counts(output)
        self.assertEqual(successes + ruins, 10000)
        self.assertEqual(unresolved, 0)
        self.assertAlmostEqual(successes / 10000, 0.5, delta=0.03)
        self.assertAlmostEqual(self.value(output, "Observed mean steps"), 100, delta=5)
        self.assertIn("Showing updates 0-60;", output)
        positions = self.path(output)
        self.assertEqual(len(positions), 61)
        self.assertEqual(positions[0], 10)
        self.assertTrue(all(0 < capital < 20 for capital in positions))
        self.assertTrue(all(abs(a - b) == 1 for a, b in zip(positions, positions[1:])))

    def test_absorbing_initial_states(self):
        for start in (0, 8):
            for probability in (0, 50, 100):
                with self.subTest(start=start, probability=probability):
                    output = self.run_program(start, 8, probability, 7, 4294967295, 1).stdout
                    self.assertEqual(self.counts(output), (7, 0, 0) if start == 8 else (0, 7, 0))
                    self.assertEqual(self.value(output, "Observed mean steps"), 0)
                    self.assertEqual(self.path(output), [start])

    def test_deterministic_walks_finish_on_the_step_limit(self):
        for probability, limit, expected_path, expected_counts in (
            (0, 3, [3, 2, 1, 0], (0, 7, 0)),
            (100, 5, [3, 4, 5, 6, 7, 8], (7, 0, 0)),
        ):
            with self.subTest(probability=probability):
                output = self.run_program(3, 8, probability, 7, 42, limit).stdout
                self.assertEqual(self.counts(output), expected_counts)
                self.assertEqual(self.value(output, "Observed mean steps"), limit)
                self.assertEqual(self.path(output), expected_path)

    def test_one_step_experiment_matches_bernoulli_model(self):
        for probability in (1, 37, 50, 99):
            with self.subTest(probability=probability):
                output = self.run_program(1, 2, probability, 10000, 42, 1).stdout
                successes, ruins, unresolved = self.counts(output)
                self.assertEqual(successes + ruins, 10000)
                self.assertEqual(unresolved, 0)
                self.assertAlmostEqual(successes / 10000, probability / 100, delta=0.025)
                self.assertEqual(self.value(output, "Observed mean steps"), 1)

    def test_all_unresolved_trials_are_reported_separately(self):
        output = self.run_program(2, 4, 50, 20, 42, 1, expected_codes=(2,)).stdout
        self.assertEqual(self.counts(output), (0, 0, 20))
        self.assertIn("batch lies in [0/20, 20/20]", output)
        self.assertEqual(self.value(output, "Observed mean min(T, step-limit)"), 1)
        self.assertNotIn("Observed mean steps:", output)
        self.assertNotIn("Observed success fraction:", output)
        self.assertIn("unresolved (per-trial step limit)", output)

    def test_mixed_unresolved_trials_keep_correct_denominator(self):
        output = self.run_program(1, 4, 50, 3, 42, 1, expected_codes=(2,)).stdout
        successes, ruins, unresolved = self.counts(output)
        self.assertEqual(successes, 0)
        self.assertGreater(ruins, 0)
        self.assertGreater(unresolved, 0)
        self.assertEqual(ruins + unresolved, 3)
        match = re.search(r"batch lies in \[(\d+)/(\d+), (\d+)/(\d+)\]", output)
        self.assertIsNotNone(match)
        self.assertEqual(tuple(map(int, match.groups())), (0, 3, unresolved, 3))
        self.assertIn("Approximate bounds:", output)
        self.assertEqual(self.value(output, "Observed mean min(T, step-limit)"), 1)

    def test_seed_reproducibility(self):
        for seed in (0, 42, 4294967295):
            with self.subTest(seed=seed):
                arguments = (3, 8, 47, 200, seed)
                first = self.run_program(*arguments).stdout
                self.assertEqual(first, self.run_program(*arguments).stdout)

    def test_help_and_upper_argument_bounds(self):
        help_result = self.run_program("--help")
        self.assertIn("Usage:", help_result.stdout)
        self.assertEqual(help_result.stderr, "")
        result = self.run_program(40, 40, 100, 10000, 4294967295, 10000)
        self.assertEqual(self.counts(result.stdout), (10000, 0, 0))

    def test_invalid_arguments(self):
        invalid_arguments = (
            ("",), ("-1",), ("+1",), (" 1",), ("1.5",), ("1x",),
            ("4294967296",), (21,), (41,), (5, 4), (0, 1), (0, 41),
            (1, 2, -1), (1, 2, 101), (1, 2, 50, 0), (1, 2, 50, 10001),
            (1, 2, 50, 1, -1), (1, 2, 50, 1, "4294967296"),
            (1, 2, 50, 1, 42, 0), (1, 2, 50, 1, 42, 10001),
            (1, 2, 50, 1, 42, 1, 9), ("--help", 1),
        )
        for arguments in invalid_arguments:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, expected_codes=(1,))
                self.assertEqual(result.stdout, "")
                self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
