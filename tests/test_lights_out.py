#!/usr/bin/env python3
"""Check the Lights Out CLI against independent first-row enumeration."""

from functools import lru_cache
import os
from pathlib import Path
import random
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def encode(rows):
    size = len(rows)
    return "/".join("".join(str((row >> column) & 1) for column in range(size))
                    for row in rows)


def from_integer(value, size):
    mask = (1 << size) - 1
    return tuple((value >> (row * size)) & mask for row in range(size))


def weight(rows):
    return sum(bin(row).count("1") for row in rows)


@lru_cache(maxsize=None)
def chase_rows(board):
    """Guess only the first press row; clearing each row forces the next one."""
    size = len(board)
    mask = (1 << size) - 1
    solutions = []
    for first in range(1 << size):
        presses = [first]
        for row in range(size - 1):
            previous = presses[row - 1] if row else 0
            presses.append(board[row] ^ presses[row] ^ previous
                           ^ ((presses[row] << 1) & mask) ^ (presses[row] >> 1))
        previous = presses[-2] if size > 1 else 0
        last = board[-1] ^ presses[-1] ^ previous
        last ^= ((presses[-1] << 1) & mask) ^ (presses[-1] >> 1)
        if last == 0:
            solutions.append(tuple(presses))
    return tuple(solutions)


def toggle_cells(presses):
    """Replay individual presses cell by cell, without row-chasing formulas."""
    size = len(presses)
    board = [0] * size
    for row in range(size):
        for column in range(size):
            if (presses[row] >> column) & 1:
                for dr, dc in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                    r, c = row + dr, column + dc
                    if 0 <= r < size and 0 <= c < size:
                        board[r] ^= 1 << c
    return tuple(board)


class LightsOutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-lights-out-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "lights_out"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "lights_out.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, expected_code=0):
        result = subprocess.run(
            [str(self.binary), *(str(argument) for argument in arguments)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        return result

    def number(self, output, label):
        matches = re.findall(rf"^{re.escape(label)}: (\d+)$", output, re.MULTILINE)
        self.assertEqual(len(matches), 1, output)
        return int(matches[0])

    def pattern(self, output, label, size):
        lines = output.splitlines()
        self.assertEqual(lines.count(label), 1, output)
        start = lines.index(label) + 1
        rows = lines[start:start + size]
        self.assertEqual(len(rows), size, output)
        for row in rows:
            self.assertRegex(row, rf"^\|[01]{{{size}}}\|$")
        return tuple(sum((value == "1") << column
                         for column, value in enumerate(row[1:-1])) for row in rows)

    def check_basis(self, output, size, nullity, solution, expected):
        self.assertEqual(self.number(output, "Kernel basis"), nullity)
        labels = re.findall(r"^Basis (\d+):$", output, re.MULTILINE)
        self.assertEqual(list(map(int, labels)), list(range(1, nullity + 1)))
        zero = (0,) * size
        span = {zero}
        for index in range(1, nullity + 1):
            basis = self.pattern(output, f"Basis {index}:", size)
            self.assertNotEqual(basis, zero)
            self.assertEqual(toggle_cells(basis), zero)
            translated = {tuple(a ^ b for a, b in zip(item, basis)) for item in span}
            self.assertEqual(len(span | translated), 2 * len(span), "dependent basis")
            span |= translated
        self.assertEqual(span, set(chase_rows(zero)))
        if solution is not None:
            affine = {tuple(a ^ b for a, b in zip(solution, item)) for item in span}
            self.assertEqual(affine, set(expected))

    def check_board(self, board, show_basis=False, arguments=None):
        size = len(board)
        expected = chase_rows(board)
        if arguments is None:
            arguments = (size, encode(board)) + (("--basis",) if show_basis else ())
        result = self.run_program(*arguments, expected_code=0 if expected else 2)
        output = result.stdout
        self.assertEqual(result.stderr, "")
        self.assertIn(f"Lights Out: {size} x {size}\n", output)
        self.assertEqual(self.pattern(output, "Input board (1=on, 0=off):", size), board)
        kernel_size = len(chase_rows((0,) * size))
        nullity = kernel_size.bit_length() - 1
        self.assertEqual(self.number(output, "Rank"), size * size - nullity)
        self.assertEqual(self.number(output, "Nullity"), nullity)
        self.assertEqual(self.number(output, "Solutions"), len(expected))
        solution = None
        if expected:
            minimum_weight = min(map(weight, expected))
            minima = [item for item in expected if weight(item) == minimum_weight]
            solution = self.pattern(output, "Minimum press pattern (1=press, 0=skip):", size)
            self.assertEqual(self.number(output, "Minimum presses"), minimum_weight)
            self.assertEqual(self.number(output, "Minimum solutions"), len(minima))
            self.assertEqual(solution, min(minima, key=encode))
            self.assertEqual(toggle_cells(solution), board)
            self.assertIn("Press each marked cell once, in any order.\n", output)
            self.assertNotIn("No solution:", output)
        else:
            self.assertIn("No solution: row reduction produced 0 = 1.\n", output)
            self.assertNotIn("Minimum", output)
            self.assertNotIn("Press each marked cell", output)
        if show_basis:
            self.check_basis(output, size, nullity, solution, expected)
        else:
            self.assertNotIn("Kernel basis:", output)
            self.assertNotRegex(output, r"(?m)^Basis \d+:")
        return output

    def test_every_board_up_to_three_by_three(self):
        for size in range(1, 4):
            for value in range(1 << (size * size)):
                with self.subTest(size=size, board=value):
                    self.check_board(from_integer(value, size))

    def test_all_on_and_off_for_every_size(self):
        # rank, minimum presses for all-on, number of minimum plans
        fixtures = ((1, 1, 1), (4, 4, 1), (9, 5, 1), (12, 4, 2), (23, 15, 4),
                    (36, 28, 1), (49, 33, 1), (64, 40, 1), (73, 25, 6), (100, 44, 1))
        for size, (rank, minimum, minimum_count) in enumerate(fixtures, 1):
            with self.subTest(size=size):
                output = self.check_board(((1 << size) - 1,) * size, arguments=(size,))
                self.assertEqual(self.number(output, "Rank"), rank)
                self.assertEqual(self.number(output, "Minimum presses"), minimum)
                self.assertEqual(self.number(output, "Minimum solutions"), minimum_count)
                zero = self.check_board((0,) * size, show_basis=True)
                self.assertEqual(self.number(zero, "Minimum presses"), 0)
                self.assertEqual(self.number(zero, "Minimum solutions"), 1)

    def test_default_and_basis_flag_positions(self):
        board = (31,) * 5
        plain = self.check_board(board, arguments=())
        self.assertEqual(plain, self.check_board(board, arguments=(5,)))
        reference = self.check_board(board, show_basis=True, arguments=("--basis",))
        for arguments in (("--basis", 5), (5, "--basis"),
                          ("--basis", 5, encode(board)),
                          (5, "--basis", encode(board)),
                          (5, encode(board), "--basis")):
            with self.subTest(arguments=arguments):
                self.assertEqual(reference, self.check_board(
                    board, show_basis=True, arguments=arguments))

    def test_row_major_tie_break_fixtures(self):
        fixtures = {
            4: "0010/1000/0001/0100",
            5: "00011/11011/11100/01110/10110",
            9: "001001100/100001101/000100010/010000101/000010000/"
               "101000010/010001000/101100001/001100100",
        }
        for size, expected in fixtures.items():
            with self.subTest(size=size):
                output = self.check_board(((1 << size) - 1,) * size, show_basis=True)
                actual = self.pattern(output, "Minimum press pattern (1=press, 0=skip):", size)
                self.assertEqual(encode(actual), expected)

    def test_unsolvable_single_corner_lights(self):
        for size in (4, 5, 9):
            with self.subTest(size=size):
                self.check_board((1,) + (0,) * (size - 1), show_basis=True)

    def test_seeded_general_and_generated_boards(self):
        rng = random.Random(20261004)
        for size in range(4, 11):
            for sample in range(6):
                with self.subTest(size=size, sample=sample):
                    board = tuple(rng.getrandbits(size) for _ in range(size))
                    self.check_board(board, show_basis=sample == 0)
                    presses = tuple(rng.getrandbits(size) for _ in range(size))
                    self.check_board(toggle_cells(presses), show_basis=sample == 0)

    def test_one_press_at_corners_and_center(self):
        for size in (1, 2, 4, 5, 8, 9, 10):
            positions = {(0, 0), (0, size - 1), (size - 1, 0),
                         (size - 1, size - 1), (size // 2, size // 2)}
            for row, column in sorted(positions):
                with self.subTest(size=size, row=row, column=column):
                    presses = [0] * size
                    presses[row] = 1 << column
                    output = self.check_board(toggle_cells(presses))
                    self.assertEqual(self.number(output, "Minimum presses"), 1)

    def test_help(self):
        result = self.run_program("--help")
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--basis", result.stdout)
        self.assertNotIn("Rank:", result.stdout)

    def test_invalid_arguments(self):
        invalid = [
            ("",), ("0",), ("11",), ("-1",), ("+2",), ("2.0",), ("2x",),
            (" 2",), ("2 ",), ("999999999999999999999999999999",),
            ("--unknown",), ("--help", "2"), ("2", "--help"),
            ("--help", "--basis"), ("--basis", "--help"),
            ("--basis", "--basis"), ("2", "--basis", "--basis"),
            ("2", "00/00", "--basis", "--basis"),
            ("2", "00/00", "extra"), ("2", "00/00", "--help"),
            ("2", ""), ("2", "00/00/00"), ("2", "000/00"), ("2", "00/000"),
            ("2", "0/00"), ("2", "00/0"), ("2", "00000"), ("2", "00//00"),
            ("2", "/00/00"), ("2", "00/00/"), ("2", "00\\00"), ("2", "00\n00"),
            ("2", "00/0x"), ("2", "00/02"), ("2", "00/0 0"),
            ("1", "10"), ("1", "/"), ("1", "\uff11"),
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.startswith("Invalid arguments.\n"))
                self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
