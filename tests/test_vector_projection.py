import math
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


class ProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="vector-projection-")
        cls.addClassCleanup(directory.cleanup)
        cls.binary = Path(directory.name) / "vector_projection"
        source = Path(__file__).resolve().parents[1] / "vector_projection.cpp"
        command = shlex.split(os.environ.get("CXX", "c++"))
        command += ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror"]
        for name in ("CPPFLAGS", "CXXFLAGS"):
            command += shlex.split(os.environ.get(name, ""))
        subprocess.run(command + [str(source), "-o", str(cls.binary)], check=True, timeout=60)

    def project(self, text, error=False):
        result = subprocess.run([str(self.binary)], input=text, text=True,
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1 if error else 0, result.stderr)
        if error:
            self.assertEqual(result.stdout, "")
            self.assertTrue(result.stderr.strip())
            return
        self.assertEqual(result.stderr, "")
        lines = result.stdout.splitlines()
        self.assertEqual([line.split(":")[0] for line in lines], ["Projection", "Remainder"])
        vectors = [list(map(float, line.split(":")[1].split())) for line in lines]
        for vector in vectors:
            self.assertEqual(len(vector), 2)
            self.assertTrue(all(math.isfinite(value) for value in vector))
        return vectors

    def test_known_answers(self):
        cases = [("3 4 1 1", [[3.5, 3.5], [-0.5, 0.5]]),
                 ("3 4 1 0", [[3, 0], [0, 4]]),
                 ("3 4 -3 -4", [[3, 4], [0, 0]]),
                 ("1 -1 2 2", [[0, 0], [1, -1]]),
                 ("0 0 2 3", [[0, 0], [0, 0]])]
        for text, expected in cases:
            with self.subTest(input=text):
                for actual, wanted in zip(self.project(text), expected):
                    for value, answer in zip(actual, wanted):
                        self.assertAlmostEqual(value, answer, places=8)

    def test_decomposition_and_perpendicular_remainder(self):
        for a, b in [([2, -7], [3, 5]), ([-4, 6], [-2, 7]), ([0.25, 1.5], [4, -3])]:
            projection, remainder = self.project(" ".join(map(str, a + b)))
            factor = sum(x * y for x, y in zip(a, b)) / sum(x * x for x in b)
            for i in range(2):
                self.assertAlmostEqual(projection[i], factor * b[i], places=8)
                self.assertAlmostEqual(projection[i] + remainder[i], a[i], places=8)
            self.assertAlmostEqual(sum(x * y for x, y in zip(remainder, b)), 0, places=7)

    def test_direction_scale_and_sign_do_not_change_projection(self):
        expected = self.project("3 4 1 2")
        for scale in (1e-200, 1e200, -1):
            self.assertEqual(self.project(f"3 4 {scale} {2 * scale}"), expected)

    def test_invalid_input_and_overflow(self):
        for text in ("", "1 2 3", "1 2 3 4 5", "3 4 0 0", "1 2 x 4",
                     "1 2 3 4x", "nan 2 3 4", "1 2 inf 4", "1e309 2 3 4",
                     "1.7e308 1.7e308 2 1"):
            with self.subTest(input=text):
                self.project(text, error=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
