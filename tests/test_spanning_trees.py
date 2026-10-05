#!/usr/bin/env python3
"""Check exact tree and edge counts by enumerating trees, without determinants."""

from fractions import Fraction
from functools import lru_cache
from itertools import combinations
from math import gcd
import os
from pathlib import Path
import random
import re
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EDGE_HEADER = "u v trees probability bridge"


def normalize(edges):
    return tuple(sorted(tuple(sorted(edge)) for edge in edges))


def encode(edges):
    return ",".join(f"{u}-{v}" for u, v in edges) or "-"


def connected(vertices, edges):
    neighbors = [set() for _ in range(vertices)]
    for u, v in edges:
        neighbors[u].add(v)
        neighbors[v].add(u)
    visited = {0}
    pending = [0]
    while pending:
        for neighbor in neighbors[pending.pop()]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    return len(visited) == vertices


@lru_cache(maxsize=None)
def enumerate_trees(vertices, edges):
    """Count acyclic subsets with n-1 edges using a disjoint-set forest."""
    inclusion = [0] * len(edges)
    if not connected(vertices, edges):
        return 0, tuple(inclusion)
    total = 0
    for chosen in combinations(range(len(edges)), vertices - 1):
        parents = list(range(vertices))

        def root(vertex):
            while parents[vertex] != vertex:
                vertex = parents[vertex]
            return vertex

        for index in chosen:
            u, v = (root(vertex) for vertex in edges[index])
            if u == v:
                break
            parents[u] = v
        else:
            total += 1
            for index in chosen:
                inclusion[index] += 1
    return total, tuple(inclusion)


def family_edges(family, size):
    if family == "path":
        return tuple((vertex, vertex + 1) for vertex in range(size - 1))
    if family == "cycle":
        return normalize((vertex, (vertex + 1) % size) for vertex in range(size))
    if family == "complete":
        return tuple(combinations(range(size), 2))
    if family == "grid":
        return normalize((row * size + column, r * size + c)
                         for row in range(size) for column in range(size)
                         for r, c in ((row + 1, column), (row, column + 1))
                         if r < size and c < size)
    raise ValueError(family)


def expected_cofactor(vertices, edges):
    matrix = [[0] * vertices for _ in range(vertices)]
    for u, v in edges:
        matrix[u][u] += 1
        matrix[v][v] += 1
        matrix[u][v] -= 1
        matrix[v][u] -= 1
    return [row[:-1] for row in matrix[:-1]]


class SpanningTreesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="maths-spanning-trees-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "spanning_trees"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "spanning_trees.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_program(self, *arguments, expected_code=0):
        result = subprocess.run(
            [str(self.binary), *(str(argument) for argument in arguments)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, expected_code, result.stdout + result.stderr)
        return result

    def number(self, output, label):
        values = re.findall(rf"^{re.escape(label)}: (\d+)$", output, re.MULTILINE)
        self.assertEqual(len(values), 1, output)
        return int(values[0])

    def check_matrix(self, output, vertices, edges):
        lines = output.splitlines()
        label = f"Cofactor (remove vertex {vertices - 1}):"
        self.assertEqual(lines.count(label), 1, output)
        start = lines.index(label) + 1
        if vertices == 1:
            self.assertEqual(lines[start], "Empty matrix: determinant 1.")
            return
        self.assertNotIn("Empty matrix:", output)
        rows = lines[start:start + vertices - 1]
        self.assertEqual(len(rows), vertices - 1)
        for row in rows:
            self.assertRegex(row, r"^\|\s*-?\d+(?:\s+-?\d+)*\s*\|$")
        actual = [list(map(int, row[1:-1].split())) for row in rows]
        self.assertEqual(actual, expected_cofactor(vertices, edges))

    def check_graph(self, family, size, edges, stats=True, arguments=None, expected=None):
        vertices = size * size if family == "grid" else size
        edges = normalize(edges)
        total, inclusion = expected if expected is not None else enumerate_trees(vertices, edges)
        self.assertEqual(total > 0, connected(vertices, edges))
        if arguments is None:
            arguments = (family, size)
            if family == "custom":
                arguments += (encode(edges),)
            if stats:
                arguments += ("--edge-stats",)
        result = self.run_program(*arguments, expected_code=0 if total else 2)
        output = result.stdout
        self.assertEqual(result.stderr, "")
        self.assertIn(f"Spanning trees: {family} (size {size})\n", output)
        self.assertEqual(self.number(output, "Vertices"), vertices)
        self.assertEqual(self.number(output, "Edges"), len(edges))
        self.assertEqual(self.number(output, "Trees"), total)
        self.check_matrix(output, vertices, edges)
        if not total:
            self.assertIn("No spanning tree: graph is disconnected.\n", output)
        else:
            self.assertNotIn("No spanning tree:", output)
        if not stats or not total:
            self.assertNotIn(EDGE_HEADER, output)
            self.assertNotIn("Inclusion sum:", output)
            return output

        self.assertEqual(output.splitlines().count(EDGE_HEADER), 1)
        rows = re.findall(r"^(\d+)\s+(\d+)\s+(\d+)\s+(\d+)/(\d+)\s+(yes|no)$",
                          output, re.MULTILINE)
        self.assertEqual(tuple((int(row[0]), int(row[1])) for row in rows), edges)
        for index, row in enumerate(rows):
            count, numerator, denominator = map(int, row[2:5])
            self.assertEqual(count, inclusion[index])
            self.assertGreater(denominator, 0)
            self.assertEqual(gcd(numerator, denominator), 1)
            self.assertEqual(Fraction(numerator, denominator), Fraction(count, total))
            remaining = edges[:index] + edges[index + 1:]
            self.assertEqual(row[5] == "yes", not connected(vertices, remaining))
            self.assertEqual(row[5] == "yes", count == total)
        self.assertEqual(self.number(output, "Inclusion sum"), sum(inclusion))
        self.assertEqual(sum(inclusion), (vertices - 1) * total)
        return output

    def test_every_labelled_graph_up_to_four_vertices(self):
        for vertices in range(1, 5):
            complete = tuple(combinations(range(vertices), 2))
            for mask in range(1 << len(complete)):
                edges = tuple(edge for index, edge in enumerate(complete) if mask & (1 << index))
                with self.subTest(vertices=vertices, mask=mask):
                    self.check_graph("custom", vertices, edges)

    def test_path_cycle_and_complete_formulas(self):
        for size in range(1, 11):
            with self.subTest(family="path", size=size):
                edges = family_edges("path", size)
                self.check_graph("path", size, edges, expected=(1, (1,) * len(edges)))
            with self.subTest(family="complete", size=size):
                edges = family_edges("complete", size)
                total = 1 if size <= 2 else size ** (size - 2)
                inclusion = 1 if size <= 2 else 2 * size ** (size - 3)
                self.check_graph("complete", size, edges,
                                 expected=(total, (inclusion,) * len(edges)))
            if size >= 3:
                with self.subTest(family="cycle", size=size):
                    edges = family_edges("cycle", size)
                    self.check_graph("cycle", size, edges,
                                     expected=(size, (size - 1,) * size))

    def test_grid_counts_and_edge_probabilities(self):
        for size, total in ((1, 1), (2, 4), (3, 192)):
            with self.subTest(size=size):
                edges = family_edges("grid", size)
                inclusion = tuple(112 if 4 in edge else 136 for edge in edges) if size == 3 else (3,) * len(edges)
                self.assertEqual(enumerate_trees(size * size, edges), (total, inclusion))
                self.check_graph("grid", size, edges, expected=(total, inclusion))

    def test_complete_ten_with_one_edge_missing(self):
        # A fixed two-edge forest occurs in 3*n^(n-4) Cayley trees if the
        # edges share a vertex, or 4*n^(n-4) if they do not.
        edges = tuple(edge for edge in family_edges("complete", 10) if edge != (0, 1))
        inclusion = tuple(17000000 if 0 in edge or 1 in edge else 16000000 for edge in edges)
        self.check_graph("custom", 10, edges, expected=(80000000, inclusion))

    def test_arbitrary_labels_and_bridges(self):
        edges = ((0, 2), (0, 4), (1, 2), (1, 3), (2, 4), (3, 5))
        expected = (3, (2, 2, 3, 3, 2, 3))
        self.assertEqual(enumerate_trees(6, edges), expected)
        self.check_graph("custom", 6, edges, expected=expected)

    def test_disconnected_components_and_zero_pivot_positions(self):
        self.check_graph("custom", 6, ((0, 1), (0, 2), (1, 2), (3, 4), (3, 5), (4, 5)))
        self.check_graph("custom", 10, ())
        for isolated in (0, 4, 9):
            with self.subTest(isolated=isolated):
                edges = tuple(edge for edge in family_edges("complete", 10) if isolated not in edge)
                self.check_graph("custom", 10, edges)

    def test_seeded_small_graphs_against_enumeration(self):
        rng = random.Random(20261005)
        for vertices in (5, 6):
            complete = tuple(combinations(range(vertices), 2))
            for sample in range(12):
                with self.subTest(vertices=vertices, sample=sample):
                    density = (0.15, 0.35, 0.6, 0.9)[sample % 4]
                    edges = tuple(edge for edge in complete if rng.random() < density)
                    self.check_graph("custom", vertices, edges)
                    permutation = list(range(vertices))
                    rng.shuffle(permutation)
                    tree = set(normalize(zip(permutation, permutation[1:])))
                    tree.update(edge for edge in complete if rng.random() < 0.4)
                    self.check_graph("custom", vertices, tuple(sorted(tree)))

    def test_edge_input_order_and_orientation_are_normalized(self):
        edges = ((0, 2), (0, 4), (1, 2), (1, 3), (2, 4), (3, 5))
        baseline = self.check_graph("custom", 6, edges)
        rng = random.Random(37)
        for _ in range(5):
            shuffled = list(edges)
            rng.shuffle(shuffled)
            shuffled = [(v, u) if rng.randrange(2) else (u, v) for u, v in shuffled]
            actual = self.check_graph("custom", 6, edges,
                                      arguments=("custom", 6, encode(shuffled), "--edge-stats"))
            self.assertEqual(actual, baseline)

    def test_defaults_and_flag_positions(self):
        grid = family_edges("grid", 3)
        self.check_graph("grid", 3, grid, stats=False, arguments=())
        self.check_graph("grid", 3, grid, arguments=("--edge-stats",))
        for family in ("path", "cycle", "complete", "grid"):
            self.check_graph(family, 3, family_edges(family, 3), stats=False, arguments=(family,))
        edges = family_edges("cycle", 4)
        baseline = self.check_graph("cycle", 4, edges)
        for arguments in (("--edge-stats", "cycle", 4), ("cycle", "--edge-stats", 4)):
            self.assertEqual(self.check_graph("cycle", 4, edges, arguments=arguments), baseline)
        baseline = self.check_graph("custom", 4, edges)
        positionals = ("custom", 4, encode(edges))
        for position in range(4):
            arguments = positionals[:position] + ("--edge-stats",) + positionals[position:]
            self.assertEqual(self.check_graph("custom", 4, edges, arguments=arguments), baseline)

    def test_help(self):
        result = self.run_program("--help")
        self.assertEqual(result.stderr, "")
        for text in ("Usage:", "--edge-stats", "path", "cycle", "complete", "grid", "custom"):
            self.assertIn(text, result.stdout)
        self.assertNotIn("Trees:", result.stdout)

    def test_invalid_arguments(self):
        invalid = [
            ("",), ("unknown",), ("3",), ("--unknown",),
            ("--help", "path"), ("path", "--help"),
            ("--help", "--edge-stats"), ("--edge-stats", "--help"),
            ("--edge-stats", "--edge-stats"),
            ("path", 3, "--edge-stats", "--edge-stats"),
            ("path", 3, "0-1"), ("grid", 2, "extra"),
            ("custom",), ("custom", 3), ("custom", 3, "--edge-stats"),
            ("custom", 3, "-", "extra"),
        ]
        for family, invalid_sizes in (("path", (0, 11)), ("complete", (0, 11)),
                                      ("cycle", (0, 1, 2, 11)), ("grid", (0, 4))):
            invalid.extend((family, size) for size in invalid_sizes)
        invalid.extend(("custom", size, "-") for size in (0, 11))
        invalid.extend(("path", size) for size in
                       ("", "-1", "+3", " 3", "3 ", "3.0", "3x", "999999999999999999999999"))
        malformed_edges = (
            "", ",", "--", "-,", ",0-1", "0-1,", "0-1,,1-2", "0-1;1-2",
            "0:1", "0/1", "0--1", "-1-0", "1--0", "0-1-2", "a-1", "0-a",
            "0.0-1", "0-1.0", "0-+1", "+0-1", " 0-1", "0 -1", "0- 1", "0-1 ",
            "0-1, 1-2", "0-1,\t1-2", "0-1\n", "0-0", "0-1,0-1", "0-1,1-0",
            "4-0", "0-4", "18446744073709551616-1", "0-18446744073709551616", "0-\uff11",
        )
        invalid.extend(("custom", 4, edges) for edges in malformed_edges)
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                result = self.run_program(*arguments, expected_code=1)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr.startswith("Invalid arguments.\n"))
                self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
