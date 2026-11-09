import math
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CosineSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="cosine-search-")
        cls.addClassCleanup(directory.cleanup)
        cls.binary = Path(directory.name) / "cosine_search"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        command += shlex.split(os.environ.get("CPPFLAGS", ""))
        command += shlex.split(os.environ.get("CXXFLAGS", ""))
        command += [str(ROOT / "cosine_search.cpp"), "-o", str(cls.binary)]
        subprocess.run(command, check=True, timeout=60)

    def run_search(self, data, *arguments, error=False):
        result = subprocess.run([str(self.binary), *arguments], input=data,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1 if error else 0, result.stderr)
        if error:
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())
            return []
        self.assertEqual(result.stderr, "")
        rows = []
        for line in result.stdout.splitlines():
            self.assertRegex(line, r"^[1-9]\d* -?\d+\.\d{6}$")
            index, score = line.split()
            rows.append((int(index), float(score)))
        return rows

    def test_parallel_orthogonal_and_opposite_vectors(self):
        actual = self.run_search("3 4\n-3 -4\n4 -3\n3 0\n0 4\n6 8\n")
        self.assertEqual(actual, [(5, 1), (4, 0.8), (3, 0.6), (2, 0), (1, -1)])

    def test_scores_against_dot_product_and_lengths(self):
        query = [2, -3, 1, 4]
        candidates = [[1, 2, 3, 4], [-2, 1, 4, 3], [3, -1, 0, 2], [-1, 0, 2, -3]]
        data = "\n".join(" ".join(map(str, row)) for row in [query, *candidates])
        expected = [(i, math.fsum(a * b for a, b in zip(query, row))
                     / (math.hypot(*query) * math.hypot(*row)))
                    for i, row in enumerate(candidates, 1)]
        expected.sort(key=lambda pair: pair[1], reverse=True)
        actual = self.run_search(data)
        self.assertEqual([i for i, _ in actual], [i for i, _ in expected])
        for (_, score), (_, reference) in zip(actual, expected):
            self.assertAlmostEqual(score, reference, delta=5.1e-7)

    def test_ties_keep_input_order_and_blank_lines_are_ignored(self):
        data = "\n 1 0\n\n0 1\n1 0\n  \n0 -1\n-1 0\n2 0\n"
        self.assertEqual(self.run_search(data), [(2, 1), (5, 1), (1, 0), (3, 0), (4, -1)])

    def test_scaling_with_large_and_subnormal_values(self):
        for query_scale, candidate_scale in ((1, 1), (1e308, 1e-310), (1e-310, 1e308)):
            with self.subTest(query=query_scale, candidate=candidate_scale):
                rows = [[query_scale] * 4]
                rows += [[candidate_scale * x for x in row] for row in
                         ([1, 1, 1, 1], [1, -1, 1, -1], [-1, -1, -1, -1], [1, 0, 0, 0])]
                data = "\n".join(" ".join(map(str, row)) for row in rows)
                self.assertEqual(self.run_search(data), [(1, 1), (4, 0.5), (2, 0), (3, -1)])

    def test_invalid_inputs_and_arguments(self):
        invalid = ["", " \n", "1 2\n", "0 0\n1 0\n", "1 0\n0 0\n",
                   "1 2\n1\n", "1\n1 2\n", "1 0\n1 0\n0 0\n",
                   "1 x\n1 2\n", "1 2\n3x 4\n"]
        invalid += [f"1 0\n{value} 1\n" for value in
                    ("nan", "inf", "-inf", "1e309", "1e-999", "1e", "--1")]
        for data in invalid:
            with self.subTest(data=data):
                self.run_search(data, error=True)
        self.run_search("1\n1\n", "--unused", error=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
